import csv
import io
from datetime import date, timedelta
from decimal import Decimal
from django.contrib.auth import get_user_model
from django.db.models import Avg, Case, Count, DecimalField, F, Q, Sum, Value, When
from django.db.models.functions import Coalesce, TruncMonth
from django.http import HttpResponse
from django.utils import timezone

from apps.accounts.models import UserRole
from apps.billing.models import Invoice, InvoiceStatus, Payment, PaymentStatus
from apps.inventory.models import Part, WorkOrderPart, WorkOrderPartStatus
from apps.service_requests.models import RequestPriority, RequestStatus, ServiceRequest
from apps.work_orders.models import WorkOrder, WorkOrderPriority, WorkOrderStatus

User = get_user_model()


class AnalyticsService:
    """
    High-performance business intelligence and reporting aggregation service.
    Executes database-level aggregations with zero memory bloat.
    """

    @staticmethod
    def parse_date_range(params):
        """
        Parses start_date and end_date from query parameters.
        Defaults to Month-To-Date (MTD) if not provided.
        """
        time_frame = params.get("time_frame", "").lower()
        today = timezone.localdate()

        if time_frame == "today":
            return today, today
        elif time_frame == "last_7_days":
            return today - timedelta(days=7), today
        elif time_frame == "last_30_days":
            return today - timedelta(days=30), today
        elif time_frame == "this_month":
            return today.replace(day=1), today
        elif time_frame == "last_month":
            first_of_this_month = today.replace(day=1)
            last_day_of_prev_month = first_of_this_month - timedelta(days=1)
            first_day_of_prev_month = last_day_of_prev_month.replace(day=1)
            return first_day_of_prev_month, last_day_of_prev_month
        elif time_frame == "this_year":
            return today.replace(month=1, day=1), today

        # Explicit start_date and end_date
        start_date_str = params.get("start_date")
        end_date_str = params.get("end_date")

        try:
            start_date = date.fromisoformat(start_date_str) if start_date_str else today.replace(day=1)
        except (ValueError, TypeError):
            start_date = today.replace(day=1)

        try:
            end_date = date.fromisoformat(end_date_str) if end_date_str else today
        except (ValueError, TypeError):
            end_date = today

        if start_date > end_date:
            start_date, end_date = end_date, start_date

        return start_date, end_date

    @classmethod
    def get_executive_overview(cls, start_date, end_date):
        """
        Calculates executive bird's-eye KPI cards: active jobs, completions,
        financial collections, and SLA metrics.
        """
        today = timezone.localdate()

        # 1. Work Orders Stats
        wo_qs = WorkOrder.objects.filter(created_at__date__range=[start_date, end_date])
        wo_stats = wo_qs.aggregate(
            total_work_orders=Count("id"),
            completed_jobs=Count(Case(When(status=WorkOrderStatus.COMPLETED, then=1))),
            in_progress_jobs=Count(Case(When(status=WorkOrderStatus.IN_PROGRESS, then=1))),
            assigned_jobs=Count(Case(When(status=WorkOrderStatus.ASSIGNED, then=1))),
            scheduled_jobs=Count(Case(When(status=WorkOrderStatus.SCHEDULED, then=1))),
            cancelled_jobs=Count(Case(When(status=WorkOrderStatus.CANCELLED, then=1))),
        )

        completed_today = WorkOrder.objects.filter(
            status=WorkOrderStatus.COMPLETED,
            actual_end__date=today,
        ).count()

        unassigned_emergencies = WorkOrder.objects.filter(
            priority=WorkOrderPriority.CRITICAL,
            assigned_technician__isnull=True,
            status__in=[WorkOrderStatus.DRAFT, WorkOrderStatus.SCHEDULED],
        ).count()

        # 2. Financial Stats
        inv_qs = Invoice.objects.filter(
            issue_date__range=[start_date, end_date],
            status__in=[InvoiceStatus.ISSUED, InvoiceStatus.PARTIALLY_PAID, InvoiceStatus.PAID],
        )
        total_billed = inv_qs.aggregate(
            total=Coalesce(Sum("total_amount"), Value(Decimal("0.00"), output_field=DecimalField()))
        )["total"]

        pmt_qs = Payment.objects.filter(
            payment_date__range=[start_date, end_date],
            payment_status=PaymentStatus.SUCCESS,
        )
        total_collected = pmt_qs.aggregate(
            total=Coalesce(Sum("amount"), Value(Decimal("0.00"), output_field=DecimalField()))
        )["total"]

        outstanding = max(Decimal("0.00"), total_billed - total_collected)

        # 3. Service Requests & SLA Stats
        sr_qs = ServiceRequest.objects.filter(created_at__date__range=[start_date, end_date])
        total_requests = sr_qs.count()
        completed_requests = sr_qs.filter(status__in=[RequestStatus.COMPLETED, RequestStatus.CLOSED]).count()

        # SLA calculation: requests completed within sla_resolution_due_at
        sla_met = sr_qs.filter(
            status__in=[RequestStatus.COMPLETED, RequestStatus.CLOSED],
            sla_resolution_due_at__isnull=False,
            updated_at__lte=F("sla_resolution_due_at"),
        ).count()

        sla_compliance_rate = (
            round((sla_met / completed_requests) * 100, 1) if completed_requests > 0 else 100.0
        )

        return {
            "period": {
                "start_date": str(start_date),
                "end_date": str(end_date),
            },
            "work_orders": {
                "total": wo_stats["total_work_orders"],
                "completed": wo_stats["completed_jobs"],
                "in_progress": wo_stats["in_progress_jobs"],
                "assigned": wo_stats["assigned_jobs"],
                "scheduled": wo_stats["scheduled_jobs"],
                "cancelled": wo_stats["cancelled_jobs"],
                "completed_today": completed_today,
                "unassigned_emergencies": unassigned_emergencies,
            },
            "finances": {
                "total_billed": float(total_billed),
                "total_collected": float(total_collected),
                "outstanding_receivables": float(outstanding),
                "collection_efficiency_pct": round(float(total_collected / total_billed * 100), 1) if total_billed > 0 else 0.0,
            },
            "sla": {
                "total_requests": total_requests,
                "completed_requests": completed_requests,
                "sla_met_count": sla_met,
                "compliance_rate_pct": sla_compliance_rate,
            },
        }

    @classmethod
    def get_revenue_analytics(cls, start_date, end_date):
        """
        Deep financial analysis: revenue breakdown by service category,
        top revenue-generating clients, and monthly revenue trends.
        """
        inv_qs = Invoice.objects.filter(
            issue_date__range=[start_date, end_date],
            status__in=[InvoiceStatus.ISSUED, InvoiceStatus.PARTIALLY_PAID, InvoiceStatus.PAID],
        )

        totals = inv_qs.aggregate(
            total_billed=Coalesce(Sum("total_amount"), Value(Decimal("0.00"), output_field=DecimalField())),
            labor_billed=Coalesce(Sum("labor_amount"), Value(Decimal("0.00"), output_field=DecimalField())),
            parts_billed=Coalesce(Sum("parts_amount"), Value(Decimal("0.00"), output_field=DecimalField())),
            service_billed=Coalesce(Sum("service_amount"), Value(Decimal("0.00"), output_field=DecimalField())),
            tax_billed=Coalesce(Sum("tax_amount"), Value(Decimal("0.00"), output_field=DecimalField())),
            discount_given=Coalesce(Sum("discount_amount"), Value(Decimal("0.00"), output_field=DecimalField())),
        )

        pmt_qs = Payment.objects.filter(
            payment_date__range=[start_date, end_date],
            payment_status=PaymentStatus.SUCCESS,
        )
        total_collected = pmt_qs.aggregate(
            total=Coalesce(Sum("amount"), Value(Decimal("0.00"), output_field=DecimalField()))
        )["total"]

        # Revenue Breakdown by Service Category
        category_breakdown = (
            inv_qs.filter(work_order__service_type__category__isnull=False)
            .values("work_order__service_type__category__id", "work_order__service_type__category__name")
            .annotate(
                category_revenue=Sum("total_amount"),
                invoice_count=Count("id"),
            )
            .order_by("-category_revenue")
        )

        categories_data = [
            {
                "category_id": str(item["work_order__service_type__category__id"]),
                "category_name": item["work_order__service_type__category__name"],
                "revenue": float(item["category_revenue"]),
                "invoice_count": item["invoice_count"],
            }
            for item in category_breakdown
        ]

        # Top 5 Customers by Billed Revenue
        customer_breakdown = (
            inv_qs.values("customer__id", "customer__company_name")
            .annotate(
                customer_revenue=Sum("total_amount"),
                invoices=Count("id"),
            )
            .order_by("-customer_revenue")[:5]
        )

        customers_data = [
            {
                "customer_id": str(item["customer__id"]),
                "customer_name": item["customer__company_name"],
                "revenue": float(item["customer_revenue"]),
                "invoice_count": item["invoices"],
            }
            for item in customer_breakdown
        ]

        # Monthly Revenue Trend (Last 12 months)
        twelve_months_ago = timezone.localdate() - timedelta(days=365)
        monthly_trend = (
            Invoice.objects.filter(
                issue_date__gte=twelve_months_ago,
                status__in=[InvoiceStatus.ISSUED, InvoiceStatus.PARTIALLY_PAID, InvoiceStatus.PAID],
            )
            .annotate(month=TruncMonth("issue_date"))
            .values("month")
            .annotate(
                monthly_billed=Sum("total_amount"),
                invoices=Count("id"),
            )
            .order_by("month")
        )

        trend_data = [
            {
                "month": item["month"].strftime("%Y-%m") if item["month"] else "",
                "billed_amount": float(item["monthly_billed"]),
                "invoice_count": item["invoices"],
            }
            for item in monthly_trend
        ]

        return {
            "period": {"start_date": str(start_date), "end_date": str(end_date)},
            "totals": {
                "total_billed": float(totals["total_billed"]),
                "total_collected": float(total_collected),
                "outstanding_balance": float(max(Decimal("0.00"), totals["total_billed"] - total_collected)),
                "labor_amount": float(totals["labor_billed"]),
                "parts_amount": float(totals["parts_billed"]),
                "service_amount": float(totals["service_billed"]),
                "tax_amount": float(totals["tax_billed"]),
                "discount_amount": float(totals["discount_given"]),
            },
            "by_service_category": categories_data,
            "top_customers": customers_data,
            "monthly_trend": trend_data,
        }

    @classmethod
    def get_technician_productivity(cls, start_date, end_date):
        """
        Individual and collective performance scorecards for field technicians.
        Tracks jobs completed, first-time fix rate, and average resolution time.
        """
        technicians = User.objects.filter(role=UserRole.TECHNICIAN, is_active=True).order_by("first_name")
        roster = []

        total_team_jobs_completed = 0
        total_team_labor_hours = Decimal("0.00")

        for tech in technicians:
            wo_tech = WorkOrder.objects.filter(
                assigned_technician=tech,
                created_at__date__range=[start_date, end_date],
            )

            stats = wo_tech.aggregate(
                assigned=Count("id"),
                completed=Count(Case(When(status=WorkOrderStatus.COMPLETED, then=1))),
                in_progress=Count(Case(When(status=WorkOrderStatus.IN_PROGRESS, then=1))),
                total_labor=Coalesce(Sum("labor_hours"), Value(Decimal("0.00"), output_field=DecimalField())),
                avg_labor=Coalesce(Avg("labor_hours"), Value(Decimal("0.00"), output_field=DecimalField())),
            )

            completed_count = stats["completed"]
            assigned_count = stats["assigned"]

            # First-Time Fix Rate: completed jobs without hold or rework
            first_time_fixes = wo_tech.filter(
                status=WorkOrderStatus.COMPLETED,
                hold_reason="",
                rejection_reason="",
            ).count()

            ftfr_pct = (
                round((first_time_fixes / completed_count) * 100, 1) if completed_count > 0 else 100.0
            )

            total_team_jobs_completed += completed_count
            total_team_labor_hours += stats["total_labor"]

            roster.append({
                "technician_id": str(tech.id),
                "name": tech.get_full_name() or tech.email,
                "email": tech.email,
                "jobs_assigned": assigned_count,
                "jobs_completed": completed_count,
                "jobs_in_progress": stats["in_progress"],
                "completion_rate_pct": round((completed_count / assigned_count * 100), 1) if assigned_count > 0 else 0.0,
                "first_time_fix_rate_pct": ftfr_pct,
                "total_labor_hours": float(stats["total_labor"]),
                "avg_job_duration_hours": round(float(stats["avg_labor"]), 2),
            })

        return {
            "period": {"start_date": str(start_date), "end_date": str(end_date)},
            "summary": {
                "active_technicians_count": len(roster),
                "total_jobs_completed": total_team_jobs_completed,
                "total_team_labor_hours": float(total_team_labor_hours),
            },
            "technicians": roster,
        }

    @classmethod
    def get_sla_compliance(cls, start_date, end_date):
        """
        SLA response and resolution adherence matrix broken down by priority level.
        """
        sr_qs = ServiceRequest.objects.filter(created_at__date__range=[start_date, end_date])
        total_requests = sr_qs.count()

        # Resolution SLA calculations
        resolved_tickets = sr_qs.filter(status__in=[RequestStatus.COMPLETED, RequestStatus.CLOSED])
        total_resolved = resolved_tickets.count()

        res_met = resolved_tickets.filter(
            sla_resolution_due_at__isnull=False,
            updated_at__lte=F("sla_resolution_due_at"),
        ).count()
        res_breached = total_resolved - res_met

        # Response SLA calculations (triaged/reviewed within sla_response_due_at)
        reviewed_tickets = sr_qs.filter(reviewed_at__isnull=False)
        total_reviewed = reviewed_tickets.count()

        resp_met = reviewed_tickets.filter(
            sla_response_due_at__isnull=False,
            reviewed_at__lte=F("sla_response_due_at"),
        ).count()
        resp_breached = total_reviewed - resp_met

        # Priority-wise breakdown
        priorities_data = []
        for prio_choice, prio_label in RequestPriority.choices:
            prio_qs = sr_qs.filter(priority=prio_choice)
            prio_total = prio_qs.count()
            prio_resolved = prio_qs.filter(status__in=[RequestStatus.COMPLETED, RequestStatus.CLOSED])
            prio_res_count = prio_resolved.count()

            prio_met = prio_resolved.filter(
                sla_resolution_due_at__isnull=False,
                updated_at__lte=F("sla_resolution_due_at"),
            ).count()

            prio_breached = prio_res_count - prio_met
            compliance_pct = round((prio_met / prio_res_count * 100), 1) if prio_res_count > 0 else 100.0

            priorities_data.append({
                "priority": prio_choice,
                "label": prio_label,
                "total_raised": prio_total,
                "resolved": prio_res_count,
                "sla_met": prio_met,
                "sla_breached": prio_breached,
                "compliance_pct": compliance_pct,
            })

        return {
            "period": {"start_date": str(start_date), "end_date": str(end_date)},
            "summary": {
                "total_tickets": total_requests,
                "total_resolved": total_resolved,
                "resolution_sla_met": res_met,
                "resolution_sla_breached": res_breached,
                "resolution_compliance_pct": round((res_met / total_resolved * 100), 1) if total_resolved > 0 else 100.0,
                "total_reviewed": total_reviewed,
                "response_sla_met": resp_met,
                "response_sla_breached": resp_breached,
                "response_compliance_pct": round((resp_met / total_reviewed * 100), 1) if total_reviewed > 0 else 100.0,
            },
            "by_priority": priorities_data,
        }

    @classmethod
    def get_inventory_analytics(cls, start_date, end_date):
        """
        Inventory consumption trends: fast-moving spare parts, total valuation
        of parts consumed on field jobs, and stock alerts.
        """
        wop_qs = WorkOrderPart.objects.filter(
            created_at__date__range=[start_date, end_date],
            status=WorkOrderPartStatus.CONSUMED,
        )

        total_units_consumed = wop_qs.aggregate(
            total_qty=Coalesce(Sum("quantity"), 0)
        )["total_qty"]

        # Calculate total consumed value: Sum(quantity * unit_price)
        total_valuation = wop_qs.annotate(
            item_total=F("quantity") * F("unit_price")
        ).aggregate(
            total_val=Coalesce(Sum("item_total"), Value(Decimal("0.00"), output_field=DecimalField()))
        )["total_val"]

        # Top 5 Most Consumed Parts
        top_parts = (
            wop_qs.values("part__id", "part__name", "part__sku")
            .annotate(
                units_consumed=Sum("quantity"),
                total_cost=Sum(F("quantity") * F("unit_price")),
            )
            .order_by("-units_consumed")[:5]
        )

        top_parts_data = [
            {
                "part_id": str(item["part__id"]),
                "name": item["part__name"],
                "sku": item["part__sku"],
                "units_consumed": item["units_consumed"],
                "total_cost": float(item["total_cost"]),
            }
            for item in top_parts
        ]

        # Low stock count
        low_stock_parts_count = Part.objects.filter(
            is_active=True,
            stock_items__quantity_on_hand__lte=F("reorder_threshold"),
        ).distinct().count()

        return {
            "period": {"start_date": str(start_date), "end_date": str(end_date)},
            "summary": {
                "total_units_consumed": total_units_consumed,
                "total_valuation_consumed": float(total_valuation),
                "low_stock_alerts_count": low_stock_parts_count,
            },
            "top_consumed_parts": top_parts_data,
        }

    @classmethod
    def export_csv_report(cls, report_type: str, start_date, end_date) -> HttpResponse:
        """
        Generates and streams formatted CSV reports for management download.
        """
        output = io.StringIO()
        writer = csv.writer(output)
        report_name = f"{report_type}_{start_date}_{end_date}.csv"

        if report_type == "work_orders":
            writer.writerow([
                "Work Order Number",
                "Customer",
                "Service Type",
                "Priority",
                "Status",
                "Technician",
                "Scheduled Start",
                "Actual End",
                "Labor Hours",
                "Created At",
            ])
            orders = (
                WorkOrder.objects.filter(created_at__date__range=[start_date, end_date])
                .select_related("customer", "service_type", "assigned_technician")
                .order_by("-created_at")
            )
            for o in orders:
                writer.writerow([
                    o.work_order_number,
                    o.customer.company_name if o.customer else "N/A",
                    o.service_type.name if o.service_type else "N/A",
                    o.priority,
                    o.status,
                    o.assigned_technician.get_full_name() if o.assigned_technician else "Unassigned",
                    o.scheduled_start.strftime("%Y-%m-%d %H:%M") if o.scheduled_start else "",
                    o.actual_end.strftime("%Y-%m-%d %H:%M") if o.actual_end else "",
                    float(o.labor_hours),
                    o.created_at.strftime("%Y-%m-%d %H:%M"),
                ])

        elif report_type == "revenue":
            writer.writerow([
                "Invoice Number",
                "Work Order",
                "Customer",
                "Status",
                "Issue Date",
                "Due Date",
                "Labor Amount (INR)",
                "Parts Amount (INR)",
                "Service Amount (INR)",
                "Tax Amount (INR)",
                "Total Amount (INR)",
                "Amount Paid (INR)",
                "Balance Due (INR)",
            ])
            invoices = (
                Invoice.objects.filter(issue_date__range=[start_date, end_date])
                .select_related("customer", "work_order")
                .order_by("-issue_date")
            )
            for inv in invoices:
                writer.writerow([
                    inv.invoice_number,
                    inv.work_order.work_order_number if inv.work_order else "N/A",
                    inv.customer.company_name if inv.customer else "N/A",
                    inv.status,
                    str(inv.issue_date),
                    str(inv.due_date or ""),
                    float(inv.labor_amount),
                    float(inv.parts_amount),
                    float(inv.service_amount),
                    float(inv.tax_amount),
                    float(inv.total_amount),
                    float(inv.amount_paid),
                    float(inv.balance_due),
                ])

        elif report_type == "technicians":
            writer.writerow([
                "Technician Name",
                "Email",
                "Jobs Assigned",
                "Jobs Completed",
                "Completion Rate (%)",
                "First-Time Fix Rate (%)",
                "Total Labor Hours",
                "Avg Job Duration (Hrs)",
            ])
            data = cls.get_technician_productivity(start_date, end_date)["technicians"]
            for t in data:
                writer.writerow([
                    t["name"],
                    t["email"],
                    t["jobs_assigned"],
                    t["jobs_completed"],
                    t["completion_rate_pct"],
                    t["first_time_fix_rate_pct"],
                    t["total_labor_hours"],
                    t["avg_job_duration_hours"],
                ])

        else:
            writer.writerow(["Error", "Invalid report_type requested."])

        response = HttpResponse(output.getvalue(), content_type="text/csv")
        response["Content-Disposition"] = f'attachment; filename="{report_name}"'
        return response

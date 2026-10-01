from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.analytics.services import AnalyticsService
from apps.core.permissions import IsAdminOrManager


class ExecutiveOverviewView(APIView):
    """
    Executive summary KPI dashboard.
    Returns high-level active work orders, daily completion metrics,
    financial collections, and SLA adherence rate.
    """

    permission_classes = [permissions.IsAuthenticated, IsAdminOrManager]

    def get(self, request):
        start_date, end_date = AnalyticsService.parse_date_range(request.query_params)
        data = AnalyticsService.get_executive_overview(start_date, end_date)
        return Response(data, status=status.HTTP_200_OK)


class RevenueAnalyticsView(APIView):
    """
    Financial performance and revenue breakdown.
    Provides total billed vs collected, service category profit share,
    top enterprise customers, and monthly revenue trajectory.
    """

    permission_classes = [permissions.IsAuthenticated, IsAdminOrManager]

    def get(self, request):
        start_date, end_date = AnalyticsService.parse_date_range(request.query_params)
        data = AnalyticsService.get_revenue_analytics(start_date, end_date)
        return Response(data, status=status.HTTP_200_OK)


class TechnicianProductivityView(APIView):
    """
    Field technician performance and utilization scorecard.
    Tracks jobs completed, first-time fix rates, and average job durations.
    """

    permission_classes = [permissions.IsAuthenticated, IsAdminOrManager]

    def get(self, request):
        start_date, end_date = AnalyticsService.parse_date_range(request.query_params)
        data = AnalyticsService.get_technician_productivity(start_date, end_date)
        return Response(data, status=status.HTTP_200_OK)


class SLAComplianceView(APIView):
    """
    Operational SLA compliance and service delivery turnaround metrics.
    Analyzes response and resolution deadlines broken down by priority level.
    """

    permission_classes = [permissions.IsAuthenticated, IsAdminOrManager]

    def get(self, request):
        start_date, end_date = AnalyticsService.parse_date_range(request.query_params)
        data = AnalyticsService.get_sla_compliance(start_date, end_date)
        return Response(data, status=status.HTTP_200_OK)


class InventoryAnalyticsView(APIView):
    """
    Spare parts and inventory consumption analytics.
    Identifies high-velocity items and total valuation consumed on work orders.
    """

    permission_classes = [permissions.IsAuthenticated, IsAdminOrManager]

    def get(self, request):
        start_date, end_date = AnalyticsService.parse_date_range(request.query_params)
        data = AnalyticsService.get_inventory_analytics(start_date, end_date)
        return Response(data, status=status.HTTP_200_OK)


class ReportExportView(APIView):
    """
    CSV report generation and download endpoint.
    Accepts:
      - report_type (required): 'work_orders', 'revenue', or 'technicians'
      - start_date (optional): YYYY-MM-DD
      - end_date (optional): YYYY-MM-DD
      - time_frame (optional): 'today', 'last_7_days', 'last_30_days', 'this_month'
    """

    permission_classes = [permissions.IsAuthenticated, IsAdminOrManager]

    def get(self, request):
        report_type = request.query_params.get("report_type", "").lower()
        valid_reports = ["work_orders", "revenue", "technicians"]

        if not report_type or report_type not in valid_reports:
            return Response(
                {
                    "error": f"Invalid or missing 'report_type'. Allowed values are: {', '.join(valid_reports)}."
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        start_date, end_date = AnalyticsService.parse_date_range(request.query_params)
        return AnalyticsService.export_csv_report(report_type, start_date, end_date)

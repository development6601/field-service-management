import datetime
from django.core.exceptions import ValidationError
from django.db import transaction as db_transaction
from django.utils import timezone

from apps.accounts.models import UserRole
from apps.contracts.models import ContractStatus, ServiceContract
from apps.work_orders.models import (
    WorkOrder,
    WorkOrderHistory,
    WorkOrderPriority,
    WorkOrderStatus,
)


class ContractService:
    """
    Domain service managing maintenance contract lifecycle, SLA enforcement,
    visit quota tracking, and automated preventive work order generation.
    """

    @staticmethod
    @db_transaction.atomic
    def activate_contract(contract: ServiceContract, performed_by=None) -> ServiceContract:
        """
        Transition a contract from DRAFT to ACTIVE.
        """
        if contract.status == ContractStatus.ACTIVE:
            return contract

        if contract.status in [ContractStatus.TERMINATED, ContractStatus.CANCELLED]:
            raise ValidationError(f"Cannot activate contract with status '{contract.status}'.")

        if contract.is_expired:
            raise ValidationError("Cannot activate an expired contract (end date is in the past).")

        contract.status = ContractStatus.ACTIVE
        if not contract.next_scheduled_date:
            today = timezone.localdate()
            contract.next_scheduled_date = max(today, contract.start_date)

        contract.save(update_fields=["status", "next_scheduled_date", "updated_at"])
        return contract

    @staticmethod
    @db_transaction.atomic
    def terminate_contract(contract: ServiceContract, reason: str, performed_by=None) -> ServiceContract:
        """
        Prematurely terminate a contract with a mandatory justification reason.
        """
        if not reason or not reason.strip():
            raise ValidationError({"reason": "A mandatory termination reason must be provided."})

        if contract.status == ContractStatus.TERMINATED:
            return contract

        contract.status = ContractStatus.TERMINATED
        contract.termination_reason = reason.strip()
        contract.terminated_at = timezone.now()
        contract.save(update_fields=["status", "termination_reason", "terminated_at", "updated_at"])
        return contract

    @staticmethod
    @db_transaction.atomic
    def generate_preventive_work_order(
        *,
        contract: ServiceContract,
        scheduled_date: datetime.date = None,
        assigned_technician=None,
        service_type=None,
        performed_by=None,
        job_instructions: str = "",
    ) -> WorkOrder:
        """
        Generate and schedule a preventive maintenance WorkOrder under the contract.
        Validates contract status, expiration, and remaining visit quota.
        """
        # 1. Validation checks
        if contract.status == ContractStatus.DRAFT:
            raise ValidationError("Contract is still in DRAFT status. Activate the contract before generating visits.")

        if contract.status in [ContractStatus.TERMINATED, ContractStatus.CANCELLED]:
            raise ValidationError(f"Cannot generate maintenance job: Contract is {contract.status.lower()}.")

        if contract.is_expired or contract.status == ContractStatus.EXPIRED:
            # Auto-update status if not already set
            if contract.status != ContractStatus.EXPIRED:
                contract.status = ContractStatus.EXPIRED
                contract.save(update_fields=["status", "updated_at"])
            raise ValidationError("Cannot generate maintenance job: Contract has expired.")

        if contract.visits_remaining <= 0:
            raise ValidationError("Cannot generate maintenance job: All allowed contract visits have been exhausted.")

        # 2. Service type resolution & verification
        if service_type:
            if contract.covered_services.exists() and not contract.covered_services.filter(id=service_type.id).exists():
                raise ValidationError(
                    f"Service '{service_type.name}' is not covered under contract {contract.contract_number}."
                )
        else:
            service_type = contract.covered_services.first()

        # 3. Technician role validation
        if assigned_technician and assigned_technician.role != UserRole.TECHNICIAN:
            raise ValidationError({"assigned_technician": "Assigned user must have role=TECHNICIAN."})

        # 4. Schedule times calculation
        target_date = scheduled_date or contract.next_scheduled_date or timezone.localdate()
        target_tz = timezone.get_current_timezone()
        scheduled_start = timezone.make_aware(
            datetime.datetime.combine(target_date, datetime.time(10, 0)), target_tz
        )
        scheduled_end = timezone.make_aware(
            datetime.datetime.combine(target_date, datetime.time(12, 30)), target_tz
        )

        initial_status = WorkOrderStatus.SCHEDULED if assigned_technician else WorkOrderStatus.ASSIGNED if assigned_technician else WorkOrderStatus.DRAFT

        # 5. Create WorkOrder
        visit_index = contract.visits_used + 1
        work_order = WorkOrder.objects.create(
            customer=contract.customer,
            service_location=contract.service_location,
            service_contract=contract,
            service_type=service_type,
            assigned_technician=assigned_technician,
            is_preventive_maintenance=True,
            status=initial_status,
            priority=WorkOrderPriority.HIGH,
            title=f"PM: {contract.title} (Visit #{visit_index})",
            description=(
                f"Periodic preventive maintenance visit #{visit_index} under contract "
                f"{contract.contract_number} ({contract.service_frequency})."
            ),
            job_instructions=job_instructions or f"Perform preventive checklist for {service_type.name if service_type else 'equipment'}.",
            scheduled_start=scheduled_start,
            scheduled_end=scheduled_end,
            estimated_duration_minutes=150,
            created_by=performed_by,
        )

        WorkOrderHistory.objects.create(
            work_order=work_order,
            from_status=WorkOrderStatus.DRAFT,
            to_status=initial_status,
            changed_by=performed_by,
            notes=f"Auto-generated preventive maintenance visit under contract {contract.contract_number}",
        )

        # 6. Advance next scheduled maintenance date
        contract.next_scheduled_date = contract.calculate_next_date_from(target_date)
        contract.save(update_fields=["next_scheduled_date", "updated_at"])

        return work_order

    @staticmethod
    @db_transaction.atomic
    def record_contract_visit_completion(work_order: WorkOrder) -> None:
        """
        When a WorkOrder linked to a ServiceContract completes, increment visits_used quota.
        """
        if not work_order.service_contract:
            return

        contract = ServiceContract.objects.select_for_update().get(id=work_order.service_contract_id)
        contract.visits_used += 1

        # Check if expired or visits exhausted
        if contract.is_expired and contract.status == ContractStatus.ACTIVE:
            contract.status = ContractStatus.EXPIRED

        contract.save(update_fields=["visits_used", "status", "updated_at"])

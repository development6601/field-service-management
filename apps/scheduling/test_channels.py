from asgiref.sync import async_to_sync
from channels.db import database_sync_to_async
from channels.testing import WebsocketCommunicator
from django.contrib.auth import get_user_model
from django.test import TransactionTestCase
from django.utils import timezone
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import TechnicianProfile, UserRole
from apps.customers.models import Customer, ServiceLocation
from apps.work_orders.models import WorkOrder, WorkOrderStatus, WorkOrderPriority
from config.asgi import application

User = get_user_model()


@database_sync_to_async
def create_test_work_order(customer, location, priority, status=None, title=""):
    kwargs = {
        "customer": customer,
        "service_location": location,
        "priority": priority,
        "title": title,
    }
    if status:
        kwargs["status"] = status
    return WorkOrder.objects.create(**kwargs)


@database_sync_to_async
def update_work_order_status(wo, new_status):
    wo.status = new_status
    wo.save()
    return wo


@database_sync_to_async
def get_technician_coords(tech):
    tech.technician_profile.refresh_from_db()
    prof = tech.technician_profile
    return (
        float(prof.current_latitude) if prof.current_latitude else None,
        float(prof.current_longitude) if prof.current_longitude else None,
    )


class ChannelsWebSocketsTests(TransactionTestCase):
    """
    Automated test suite for Phase 19 Real-Time WebSockets & Django Channels.
    Tests ASGI routing, JWT authentication middleware, Dispatcher Board broadcasts,
    technician location pings, and role-based access security.
    """

    def setUp(self):
        # 1. Admin user
        self.admin = User.objects.create_user(
            email="admin.ws@fsm.com",
            password="AdminPassword123!",
            first_name="Admin",
            last_name="User",
            role=UserRole.ADMIN,
        )
        self.admin_token = str(RefreshToken.for_user(self.admin).access_token)

        # 2. Dispatcher user
        self.dispatcher = User.objects.create_user(
            email="dispatcher.ws@fsm.com",
            password="DispatcherPassword123!",
            first_name="Dispatcher",
            last_name="User",
            role=UserRole.DISPATCHER,
        )
        self.dispatcher_token = str(RefreshToken.for_user(self.dispatcher).access_token)

        # 3. Technician user
        self.technician = User.objects.create_user(
            email="tech.ws@fsm.com",
            password="TechPassword123!",
            first_name="Ramesh",
            last_name="Sharma",
            role=UserRole.TECHNICIAN,
        )
        self.tech_token = str(RefreshToken.for_user(self.technician).access_token)
        TechnicianProfile.objects.create(
            user=self.technician,
            skills=["HVAC"],
            is_available=True,
        )

        # 4. Customer user
        self.customer_user = User.objects.create_user(
            email="client.ws@fsm.com",
            password="ClientPassword123!",
            first_name="Client",
            last_name="User",
            role=UserRole.CUSTOMER,
        )
        self.customer_token = str(RefreshToken.for_user(self.customer_user).access_token)

        # Customer entity
        self.customer = Customer.objects.create(
            company_name="Apex Healthcare WS",
            primary_contact_name="Dr. Apex",
            email="contact@apexws.com",
            phone="+919876543210",
        )
        self.location = ServiceLocation.objects.create(
            customer=self.customer,
            location_name="Main Campus",
            address_line1="Sector 62",
            city="Noida",
            state="UP",
            postal_code="201301",
            is_primary=True,
        )

    def test_dispatcher_board_connect_authenticated_admin(self):
        """Admin connects to Dispatcher Board WebSocket and receives confirmation handshake."""
        async def _test():
            communicator = WebsocketCommunicator(
                application, f"/ws/dispatcher/board/?token={self.admin_token}"
            )
            connected, _ = await communicator.connect()
            self.assertTrue(connected)

            response = await communicator.receive_json_from()
            self.assertEqual(response["event"], "CONNECTED")
            self.assertEqual(response["room"], "dispatcher_board")
            self.assertEqual(response["user"], self.admin.email)
            self.assertEqual(response["role"], UserRole.ADMIN)

            await communicator.disconnect()

        async_to_sync(_test)()

    def test_dispatcher_board_connect_dispatcher_role(self):
        """Dispatcher connects to Dispatcher Board WebSocket successfully."""
        async def _test():
            communicator = WebsocketCommunicator(
                application, f"/ws/dispatcher/board/?token={self.dispatcher_token}"
            )
            connected, _ = await communicator.connect()
            self.assertTrue(connected)

            response = await communicator.receive_json_from()
            self.assertEqual(response["event"], "CONNECTED")
            self.assertEqual(response["role"], UserRole.DISPATCHER)

            await communicator.disconnect()

        async_to_sync(_test)()

    def test_dispatcher_board_rejects_customer(self):
        """Customer role is strictly forbidden from connecting to Dispatcher Board."""
        async def _test():
            communicator = WebsocketCommunicator(
                application, f"/ws/dispatcher/board/?token={self.customer_token}"
            )
            connected, _ = await communicator.connect()
            self.assertFalse(connected)

        async_to_sync(_test)()

    def test_dispatcher_board_rejects_unauthenticated(self):
        """Unauthenticated connection with missing token is rejected."""
        async def _test():
            communicator = WebsocketCommunicator(application, "/ws/dispatcher/board/")
            connected, _ = await communicator.connect()
            self.assertFalse(connected)

        async_to_sync(_test)()

    def test_dispatcher_board_ping_pong_heartbeat(self):
        """Connected dispatcher can send heartbeat ping and receive pong."""
        async def _test():
            communicator = WebsocketCommunicator(
                application, f"/ws/dispatcher/board/?token={self.admin_token}"
            )
            connected, _ = await communicator.connect()
            self.assertTrue(connected)
            await communicator.receive_json_from()  # Handshake

            # Send ping
            await communicator.send_json_to({"type": "ping"})
            response = await communicator.receive_json_from()
            self.assertEqual(response["event"], "PONG")

            await communicator.disconnect()

        async_to_sync(_test)()

    def test_work_order_created_broadcasts_to_dispatcher_board(self):
        """Creating a Work Order triggers an instant broadcast to the Dispatcher Board."""
        async def _test():
            communicator = WebsocketCommunicator(
                application, f"/ws/dispatcher/board/?token={self.admin_token}"
            )
            connected, _ = await communicator.connect()
            self.assertTrue(connected)
            await communicator.receive_json_from()  # Handshake

            # Create Work Order in DB via database_sync_to_async
            wo = await create_test_work_order(
                self.customer,
                self.location,
                WorkOrderPriority.HIGH,
                title="AC Compressor Breakdown",
            )

            response = await communicator.receive_json_from()
            self.assertEqual(response["event"], "WORK_ORDER_CREATED")
            self.assertEqual(response["data"]["work_order_id"], str(wo.id))
            self.assertEqual(response["data"]["work_order_number"], wo.work_order_number)

            await communicator.disconnect()

        async_to_sync(_test)()

    def test_work_order_status_change_broadcasts_to_dispatcher_board(self):
        """Changing Work Order status triggers an instant transition broadcast."""
        async def _test():
            wo = await create_test_work_order(
                self.customer,
                self.location,
                WorkOrderPriority.MEDIUM,
                status=WorkOrderStatus.DRAFT,
                title="Regular Filter Cleaning",
            )

            communicator = WebsocketCommunicator(
                application, f"/ws/dispatcher/board/?token={self.admin_token}"
            )
            connected, _ = await communicator.connect()
            self.assertTrue(connected)
            await communicator.receive_json_from()  # Handshake

            # Update status via database_sync_to_async
            await update_work_order_status(wo, WorkOrderStatus.SCHEDULED)

            response = await communicator.receive_json_from()
            self.assertEqual(response["event"], "WORK_ORDER_STATUS_CHANGED")
            self.assertEqual(response["data"]["old_status"], WorkOrderStatus.DRAFT)
            self.assertEqual(response["data"]["new_status"], WorkOrderStatus.SCHEDULED)

            await communicator.disconnect()

        async_to_sync(_test)()

    def test_technician_location_ping_updates_db_and_broadcasts(self):
        """Technician streams location ping, updating profile and broadcasting to dispatchers."""
        async def _test():
            # 1. Dispatcher connects
            dispatcher_comm = WebsocketCommunicator(
                application, f"/ws/dispatcher/board/?token={self.dispatcher_token}"
            )
            d_connected, _ = await dispatcher_comm.connect()
            self.assertTrue(d_connected)
            await dispatcher_comm.receive_json_from()  # Handshake

            # 2. Technician connects
            tech_comm = WebsocketCommunicator(
                application, f"/ws/technician/tracking/?token={self.tech_token}"
            )
            t_connected, _ = await tech_comm.connect()
            self.assertTrue(t_connected)
            await tech_comm.receive_json_from()  # Handshake

            # 3. Technician sends GPS ping
            await tech_comm.send_json_to(
                {
                    "type": "location_ping",
                    "latitude": 19.0760,
                    "longitude": 72.8777,
                    "is_available": True,
                }
            )

            # Technician receives ACK
            tech_response = await tech_comm.receive_json_from()
            self.assertEqual(tech_response["event"], "LOCATION_ACK")

            # Dispatcher receives live broadcast
            dispatcher_response = await dispatcher_comm.receive_json_from()
            self.assertEqual(dispatcher_response["event"], "TECHNICIAN_LOCATION_UPDATED")
            self.assertEqual(dispatcher_response["data"]["technician_id"], str(self.technician.id))
            self.assertEqual(dispatcher_response["data"]["latitude"], 19.0760)

            # Verify Database updated
            lat, lon = await get_technician_coords(self.technician)
            self.assertAlmostEqual(lat, 19.0760, places=4)
            self.assertAlmostEqual(lon, 72.8777, places=4)

            await tech_comm.disconnect()
            await dispatcher_comm.disconnect()

        async_to_sync(_test)()

# ruff: noqa: E501  (reference data reads better one record per line)
"""Static reference data for the demo seed: three home-service businesses.

Northside Home Services is the business every demo login belongs to. Harbor
Plumbing & Heating and BrightSpace Cleaning Co. exist so there is always another
tenant's data sitting in the same database - which is what makes tenant
isolation something you can actually try, not just read about.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TypedDict

from serviceflow.db.models.enums import Role

DEMO_PASSWORD = "demo1234"


class ServiceSpec(TypedDict):
    name: str
    description: str
    base_price: Decimal
    duration_minutes: int


class EmployeeSpec(TypedDict):
    first_name: str
    last_name: str
    email: str
    job_title: str
    services: list[str]
    can_sign_in: bool


class AccountSpec(TypedDict):
    email: str
    first_name: str
    last_name: str
    role: Role


class NamedCustomer(TypedDict):
    first_name: str
    last_name: str
    email: str
    phone: str
    address: str
    notes: str | None
    can_sign_in: bool


class Composition(TypedDict):
    past_completed: int
    past_cancelled: int
    past_rejected: int
    future_confirmed: int
    future_pending: int


class TenantSpec(TypedDict):
    slug: str
    name: str
    email: str
    phone: str
    timezone: str
    address: str
    accounts: list[AccountSpec]
    services: list[ServiceSpec]
    employees: list[EmployeeSpec]
    named_customers: list[NamedCustomer]
    customer_count: int
    cities: list[str]
    area_code: str
    composition: Composition
    customer_requests: list[str | None]
    internal_notes: list[str]
    visible_notes: list[str]


PLATFORM_ADMIN: AccountSpec = {
    "email": "admin@serviceflow.demo",
    "first_name": "Taylor",
    "last_name": "Brooks",
    "role": Role.OWNER,  # unused: platform administration is a user flag, not a role
}

STREETS = [
    "Maple Ave",
    "Oak Street",
    "Ridge Road",
    "Elm Court",
    "Hinman Ave",
    "Central Street",
    "Lake Street",
    "Park Place",
    "Greenwood Ave",
    "Church Street",
    "Washington Ave",
    "Forest Ave",
    "Grove Street",
    "Cedar Lane",
    "Birch Drive",
    "Willow Way",
    "Highland Ave",
    "Prospect Street",
    "Linden Ave",
    "Walnut Street",
]

FIRST_NAMES = [
    "Aaron", "Adriana", "Alan", "Alice", "Amara", "Andre", "Angela", "Anita", "Beatriz",
    "Ben", "Bianca", "Caleb", "Camille", "Carlos", "Cassandra", "Claire", "Damon", "David",
    "Deepa", "Diego", "Elena", "Elias", "Emma", "Farah", "Felix", "Gabriel", "Grace",
    "Hannah", "Hassan", "Helena", "Ian", "Imani", "Isabel", "Jack", "Jasmine", "Javier",
    "Jonas", "Julia", "Kai", "Karim", "Katherine", "Kenji", "Laila", "Leo", "Lucia",
    "Malik", "Marco", "Mei", "Miguel", "Naomi", "Nathan", "Nia", "Oliver", "Omar",
    "Paloma", "Patrick", "Rachel", "Rafael", "Rebecca", "Ruben", "Samira", "Sean",
    "Simone", "Tara", "Theo", "Tomas", "Valeria", "Victor", "Wei", "Yara", "Zoe",
]  # fmt: skip

LAST_NAMES = [
    "Abbott", "Adeyemi", "Alvarez", "Bennett", "Bergman", "Bishop", "Cabrera", "Castillo",
    "Chen", "Collins", "Dawson", "Delgado", "Donovan", "Ellison", "Farrell", "Fischer",
    "Foster", "Garcia", "Greene", "Hampton", "Hayes", "Holloway", "Ibrahim", "Jensen",
    "Kaplan", "Keller", "Lambert", "Larsen", "Lopez", "Maddox", "Mendoza", "Moreau",
    "Murphy", "Nakamura", "Novak", "Okafor", "Olsen", "Ortiz", "Palmer", "Quinn",
    "Ramirez", "Reyes", "Richter", "Santos", "Schneider", "Shapiro", "Sullivan", "Takahashi",
    "Torres", "Vance", "Vargas", "Walsh", "Whitaker", "Young", "Zimmerman",
]  # fmt: skip

CUSTOMER_NOTES = [
    None,
    None,
    None,
    "Gate code 4412. Friendly dog in the backyard.",
    "Prefers a text 30 minutes before arrival.",
    "Park in the alley behind the garage.",
    "Tenant-occupied; coordinate access with the property manager.",
    "Older home - please bring shoe covers.",
    "Works from home; mornings are best.",
]


def _customer(
    first: str, last: str, email: str, phone: str, address: str, notes: str | None = None
) -> NamedCustomer:
    return {
        "first_name": first,
        "last_name": last,
        "email": email,
        "phone": phone,
        "address": address,
        "notes": notes,
        "can_sign_in": email.endswith("@serviceflow.demo"),
    }


NORTHSIDE: TenantSpec = {
    "slug": "northside-home-services",
    "name": "Northside Home Services",
    "email": "office@northsidehome.demo",
    "phone": "+1 (847) 555-0142",
    "timezone": "America/Chicago",
    "address": "1820 Ridge Ave, Evanston, IL 60201",
    "accounts": [
        {
            "email": "owner@serviceflow.demo",
            "first_name": "Dana",
            "last_name": "Whitfield",
            "role": Role.OWNER,
        },
        {
            "email": "manager@serviceflow.demo",
            "first_name": "Marcus",
            "last_name": "Hale",
            "role": Role.MANAGER,
        },
        {
            "email": "dispatcher@serviceflow.demo",
            "first_name": "Priya",
            "last_name": "Shah",
            "role": Role.DISPATCHER,
        },
        {
            "email": "analyst@serviceflow.demo",
            "first_name": "Kevin",
            "last_name": "Tran",
            "role": Role.ANALYST,
        },
    ],
    "services": [
        {
            "name": "HVAC Inspection",
            "description": "Full heating and cooling system check: filters, coils, refrigerant and safety controls.",
            "base_price": Decimal("129.00"),
            "duration_minutes": 60,
        },
        {
            "name": "Emergency Plumbing Repair",
            "description": "Same-day response for leaks, burst pipes and failed fixtures.",
            "base_price": Decimal("289.00"),
            "duration_minutes": 120,
        },
        {
            "name": "Preventive Maintenance",
            "description": "Seasonal tune-up for furnaces, air conditioners and water heaters.",
            "base_price": Decimal("149.00"),
            "duration_minutes": 90,
        },
        {
            "name": "Water Heater Installation",
            "description": "Remove and replace a tank or tankless water heater, including permit and haul-away.",
            "base_price": Decimal("1450.00"),
            "duration_minutes": 240,
        },
        {
            "name": "Drain Cleaning",
            "description": "Clear slow or blocked kitchen, bath and main drains with a camera inspection.",
            "base_price": Decimal("179.00"),
            "duration_minutes": 60,
        },
        {
            "name": "Electrical Safety Inspection",
            "description": "Panel, breaker, outlet and GFCI testing with a written report.",
            "base_price": Decimal("199.00"),
            "duration_minutes": 90,
        },
        {
            "name": "Consultation",
            "description": "On-site assessment and written quote for larger projects.",
            "base_price": Decimal("0.00"),
            "duration_minutes": 30,
        },
    ],
    "employees": [
        {
            "first_name": "Alex",
            "last_name": "Morgan",
            "email": "employee@serviceflow.demo",
            "job_title": "HVAC Technician",
            "services": ["HVAC Inspection", "Preventive Maintenance", "Consultation"],
            "can_sign_in": True,
        },
        {
            "first_name": "Chris",
            "last_name": "Lee",
            "email": "chris.lee@northsidehome.demo",
            "job_title": "Plumbing Technician",
            "services": [
                "Emergency Plumbing Repair",
                "Water Heater Installation",
                "Drain Cleaning",
                "Preventive Maintenance",
            ],
            "can_sign_in": False,
        },
        {
            "first_name": "Jordan",
            "last_name": "Patel",
            "email": "jordan.patel@northsidehome.demo",
            "job_title": "Field Technician",
            "services": [
                "HVAC Inspection",
                "Preventive Maintenance",
                "Drain Cleaning",
                "Consultation",
            ],
            "can_sign_in": False,
        },
        {
            "first_name": "Maya",
            "last_name": "Brooks",
            "email": "maya.brooks@northsidehome.demo",
            "job_title": "Licensed Electrician",
            "services": ["Electrical Safety Inspection", "Consultation"],
            "can_sign_in": False,
        },
        {
            "first_name": "Sam",
            "last_name": "Rivera",
            "email": "sam.rivera@northsidehome.demo",
            "job_title": "Senior HVAC Technician",
            "services": [
                "HVAC Inspection",
                "Preventive Maintenance",
                "Water Heater Installation",
                "Consultation",
            ],
            "can_sign_in": False,
        },
        {
            "first_name": "Nina",
            "last_name": "Kowalski",
            "email": "nina.kowalski@northsidehome.demo",
            "job_title": "Apprentice Technician",
            "services": ["Drain Cleaning", "Preventive Maintenance"],
            "can_sign_in": False,
        },
    ],
    "named_customers": [
        _customer(
            "Sarah",
            "Mitchell",
            "customer@serviceflow.demo",
            "+1 (847) 555-0188",
            "412 Maple Ave, Evanston, IL 60201",
            "Prefers a text 30 minutes before arrival.",
        ),
        _customer(
            "James",
            "Carter",
            "james.carter@example.com",
            "+1 (847) 555-0123",
            "2230 Central Street, Evanston, IL 60201",
            "Gate code 4412. Friendly dog in the backyard.",
        ),
        _customer(
            "Emily",
            "Rodriguez",
            "emily.rodriguez@example.com",
            "+1 (847) 555-0164",
            "815 Linden Ave, Wilmette, IL 60091",
        ),
        _customer(
            "Michael",
            "Thompson",
            "michael.thompson@example.com",
            "+1 (847) 555-0107",
            "5021 Oakton Street, Skokie, IL 60077",
        ),
        _customer(
            "Olivia",
            "Bennett",
            "olivia.bennett@example.com",
            "+1 (773) 555-0139",
            "1432 W Farwell Ave, Chicago, IL 60626",
            "Tenant-occupied; coordinate access with the property manager.",
        ),
        _customer(
            "Daniel",
            "Nguyen",
            "daniel.nguyen@example.com",
            "+1 (847) 555-0175",
            "3901 Glenview Road, Glenview, IL 60025",
        ),
        _customer(
            "Rachel",
            "Kim",
            "rachel.kim@example.com",
            "+1 (847) 555-0152",
            "6710 N Lincoln Ave, Lincolnwood, IL 60712",
            "Works from home; mornings are best.",
        ),
    ],
    "customer_count": 80,
    "cities": [
        "Evanston, IL 60201",
        "Evanston, IL 60202",
        "Skokie, IL 60076",
        "Wilmette, IL 60091",
        "Chicago, IL 60626",
        "Lincolnwood, IL 60712",
        "Glenview, IL 60025",
    ],
    "area_code": "847",
    "composition": {
        "past_completed": 150,
        "past_cancelled": 24,
        "past_rejected": 8,
        "future_confirmed": 44,
        "future_pending": 14,
    },
    "customer_requests": [
        None,
        None,
        "The upstairs AC isn't keeping up in the afternoons.",
        "Water heater is making a popping noise.",
        "Kitchen sink has been draining slowly for a week.",
        "Annual furnace check before winter, please.",
        "Breaker for the garage keeps tripping.",
        "Buying this house - want everything checked before closing.",
    ],
    "internal_notes": [
        "Replaced the 16x25 filter; recommended upgrading to MERV 11.",
        "Condensate line was partially blocked - flushed and treated.",
        "Anode rod is badly corroded; quoted a replacement.",
        "Customer asked for a quote on a smart thermostat.",
        "Shutoff valve under the kitchen sink is seized - flag for the next visit.",
        "Panel is a 1970s Federal Pacific; recommended replacement in writing.",
    ],
    "visible_notes": [
        "Your system passed inspection. We replaced the filter and cleaned the coils.",
        "We cleared the drain line and tested flow - everything is draining normally.",
        "Water heater flushed and sediment removed; it should run quieter now.",
        "All outlets tested. We replaced the GFCI outlet in the garage.",
        "Refrigerant levels are within spec. Next tune-up recommended in 12 months.",
    ],
}

HARBOR: TenantSpec = {
    "slug": "harbor-plumbing",
    "name": "Harbor Plumbing & Heating",
    "email": "service@harborplumbing.demo",
    "phone": "+1 (617) 555-0190",
    "timezone": "America/New_York",
    "address": "77 Hancock Street, Quincy, MA 02171",
    "accounts": [
        {
            "email": "harbor.owner@serviceflow.demo",
            "first_name": "Rosa",
            "last_name": "Delgado",
            "role": Role.OWNER,
        },
    ],
    "services": [
        {
            "name": "Emergency Plumbing Repair",
            "description": "24/7 response for leaks and burst pipes.",
            "base_price": Decimal("310.00"),
            "duration_minutes": 120,
        },
        {
            "name": "Drain Cleaning",
            "description": "Hydro-jetting and snaking for blocked drains.",
            "base_price": Decimal("165.00"),
            "duration_minutes": 60,
        },
        {
            "name": "Boiler Service",
            "description": "Annual boiler cleaning, combustion test and safety check.",
            "base_price": Decimal("219.00"),
            "duration_minutes": 90,
        },
        {
            "name": "Sump Pump Installation",
            "description": "New sump pump with battery backup and check valve.",
            "base_price": Decimal("890.00"),
            "duration_minutes": 180,
        },
    ],
    "employees": [
        {
            "first_name": "Tom",
            "last_name": "Walsh",
            "email": "tom.walsh@harborplumbing.demo",
            "job_title": "Master Plumber",
            "services": [
                "Emergency Plumbing Repair",
                "Drain Cleaning",
                "Boiler Service",
                "Sump Pump Installation",
            ],
            "can_sign_in": False,
        },
        {
            "first_name": "Ana",
            "last_name": "Souza",
            "email": "ana.souza@harborplumbing.demo",
            "job_title": "Plumbing Technician",
            "services": ["Emergency Plumbing Repair", "Drain Cleaning", "Boiler Service"],
            "can_sign_in": False,
        },
        {
            "first_name": "Derek",
            "last_name": "Fitzgerald",
            "email": "derek.fitzgerald@harborplumbing.demo",
            "job_title": "Apprentice Plumber",
            "services": ["Drain Cleaning", "Sump Pump Installation"],
            "can_sign_in": False,
        },
    ],
    "named_customers": [],
    "customer_count": 30,
    "cities": ["Quincy, MA 02169", "Braintree, MA 02184", "Milton, MA 02186", "Weymouth, MA 02188"],
    "area_code": "617",
    "composition": {
        "past_completed": 50,
        "past_cancelled": 8,
        "past_rejected": 3,
        "future_confirmed": 14,
        "future_pending": 5,
    },
    "customer_requests": [
        None,
        None,
        "Basement flooded after the storm.",
        "No hot water since Sunday.",
    ],
    "internal_notes": [
        "Main stack has a hairline crack above the cleanout.",
        "Boiler pressure was low; topped up and checked the expansion tank.",
    ],
    "visible_notes": [
        "Drain cleared and camera-inspected - no root intrusion found.",
        "Boiler serviced and passed the combustion test.",
    ],
}

BRIGHTSPACE: TenantSpec = {
    "slug": "brightspace-cleaning",
    "name": "BrightSpace Cleaning Co.",
    "email": "hello@brightspacecleaning.demo",
    "phone": "+1 (303) 555-0117",
    "timezone": "America/Denver",
    "address": "2400 E 17th Ave, Denver, CO 80206",
    "accounts": [
        {
            "email": "brightspace.owner@serviceflow.demo",
            "first_name": "Grace",
            "last_name": "Holloway",
            "role": Role.OWNER,
        },
    ],
    "services": [
        {
            "name": "Standard Home Cleaning",
            "description": "Kitchen, bathrooms, dusting, vacuuming and mopping.",
            "base_price": Decimal("140.00"),
            "duration_minutes": 120,
        },
        {
            "name": "Deep Cleaning",
            "description": "Everything in a standard clean plus baseboards, inside appliances and grout.",
            "base_price": Decimal("320.00"),
            "duration_minutes": 240,
        },
        {
            "name": "Move-Out Cleaning",
            "description": "Empty-home clean to landlord inspection standard.",
            "base_price": Decimal("420.00"),
            "duration_minutes": 300,
        },
        {
            "name": "Window Cleaning",
            "description": "Interior and exterior glass, tracks and screens.",
            "base_price": Decimal("110.00"),
            "duration_minutes": 90,
        },
    ],
    "employees": [
        {
            "first_name": "Lena",
            "last_name": "Park",
            "email": "lena.park@brightspacecleaning.demo",
            "job_title": "Cleaning Lead",
            "services": [
                "Standard Home Cleaning",
                "Deep Cleaning",
                "Move-Out Cleaning",
                "Window Cleaning",
            ],
            "can_sign_in": False,
        },
        {
            "first_name": "Carlos",
            "last_name": "Mendez",
            "email": "carlos.mendez@brightspacecleaning.demo",
            "job_title": "Cleaning Specialist",
            "services": ["Standard Home Cleaning", "Deep Cleaning", "Window Cleaning"],
            "can_sign_in": False,
        },
        {
            "first_name": "Aisha",
            "last_name": "Johnson",
            "email": "aisha.johnson@brightspacecleaning.demo",
            "job_title": "Cleaning Specialist",
            "services": ["Standard Home Cleaning", "Move-Out Cleaning"],
            "can_sign_in": False,
        },
    ],
    "named_customers": [],
    "customer_count": 30,
    "cities": ["Denver, CO 80206", "Denver, CO 80218", "Aurora, CO 80012", "Lakewood, CO 80226"],
    "area_code": "303",
    "composition": {
        "past_completed": 50,
        "past_cancelled": 8,
        "past_rejected": 2,
        "future_confirmed": 14,
        "future_pending": 5,
    },
    "customer_requests": [None, None, "Moving out on the 30th.", "Please use unscented products."],
    "internal_notes": ["Oven needed a second degreasing pass.", "Client asked to skip the office."],
    "visible_notes": [
        "All rooms cleaned; we left the windows open to air out the kitchen.",
        "Move-out clean complete and photographed for your landlord.",
    ],
}

TENANTS: list[TenantSpec] = [NORTHSIDE, HARBOR, BRIGHTSPACE]
DEMO_TENANT_SLUG = NORTHSIDE["slug"]


class ShiftSpec(TypedDict):
    days: list[int]  # 0 = Monday
    start: str
    end: str


WEEKDAYS = [0, 1, 2, 3, 4]

# Local wall-clock hours in each business's own timezone.
WEEKLY_SHIFTS: dict[str, list[ShiftSpec]] = {
    "employee@serviceflow.demo": [{"days": WEEKDAYS, "start": "08:00", "end": "17:00"}],
    "chris.lee@northsidehome.demo": [{"days": WEEKDAYS, "start": "07:00", "end": "15:30"}],
    "jordan.patel@northsidehome.demo": [{"days": [1, 2, 3, 4, 5], "start": "09:00", "end": "18:00"}],
    "maya.brooks@northsidehome.demo": [{"days": [0, 1, 2, 3], "start": "08:00", "end": "18:00"}],
    "sam.rivera@northsidehome.demo": [{"days": WEEKDAYS, "start": "10:00", "end": "19:00"}],
    "nina.kowalski@northsidehome.demo": [
        {"days": [0, 2, 4], "start": "08:00", "end": "12:00"},
        {"days": [0, 2, 4], "start": "13:00", "end": "17:00"},
    ],
    "tom.walsh@harborplumbing.demo": [{"days": WEEKDAYS, "start": "07:00", "end": "16:00"}],
    "ana.souza@harborplumbing.demo": [{"days": WEEKDAYS, "start": "09:00", "end": "18:00"}],
    "derek.fitzgerald@harborplumbing.demo": [{"days": [1, 2, 3, 4, 5], "start": "08:00", "end": "17:00"}],
    "lena.park@brightspacecleaning.demo": [{"days": WEEKDAYS, "start": "08:00", "end": "16:00"}],
    "carlos.mendez@brightspacecleaning.demo": [{"days": [1, 2, 3, 4, 5], "start": "09:00", "end": "17:00"}],
    "aisha.johnson@brightspacecleaning.demo": [{"days": [0, 1, 2, 3], "start": "07:30", "end": "15:30"}],
}  # fmt: skip

# (days from today, available, start, end, reason)
OVERRIDE_SPECS: dict[str, list[tuple[int, bool, str | None, str | None, str]]] = {
    "sam.rivera@northsidehome.demo": [(3, False, None, None, "Manufacturer training")],
    "maya.brooks@northsidehome.demo": [(1, True, "12:00", "18:00", "Dentist in the morning")],
    "jordan.patel@northsidehome.demo": [(8, False, None, None, "Vacation"), (9, False, None, None, "Vacation")],
    "ana.souza@harborplumbing.demo": [(2, False, None, None, "Out sick")],
}  # fmt: skip

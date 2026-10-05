from fastapi import APIRouter
from app.api.health import router as health_router
from app.api.profiles import router as profiles_router
from app.api.families import router as families_router
from app.api.consents import router as consents_router
from app.api.health_records import router as health_records_router
from app.api.medicines import router as medicines_router
from app.api.medicine_schedules import router as medicine_schedules_router
from app.api.medicine_logs import router as medicine_logs_router
from app.api.emergency_contacts import router as emergency_contacts_router
from app.api.emergency_sos import router as emergency_sos_router
from app.api.medical_reports import router as medical_reports_router
from app.api.notifications import router as notifications_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(profiles_router)
api_router.include_router(families_router)
api_router.include_router(consents_router)
api_router.include_router(health_records_router)
api_router.include_router(medicines_router)
api_router.include_router(medicine_schedules_router)
api_router.include_router(medicine_logs_router)
api_router.include_router(emergency_contacts_router)
api_router.include_router(emergency_sos_router)
api_router.include_router(medical_reports_router)
api_router.include_router(notifications_router)

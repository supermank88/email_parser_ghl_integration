from django.urls import path
from . import views

app_name = 'inbound'

urlpatterns = [
    path('webhook/sendgrid/', views.sendgrid_inbound, name='sendgrid_inbound'),
    path('emails/', views.email_list, name='email_list'),
    path('emails/<int:pk>/', views.email_detail, name='email_detail'),
    # NDA: list contacts that have contact_id + listing_id + phone
    path('nda/contacts/', views.nda_contacts_list, name='nda_contacts_list'),
    # NDA page: /nda/<contact_id>/?listing_id=...&listing_name=...&created=...
    path('nda/<str:contact_id>/', views.nda_page, name='nda_page'),
]

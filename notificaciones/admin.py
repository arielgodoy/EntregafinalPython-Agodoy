from django.contrib import admin

from .models import Notification, DemoSeedLog

admin.site.register(Notification)
admin.site.register(DemoSeedLog)

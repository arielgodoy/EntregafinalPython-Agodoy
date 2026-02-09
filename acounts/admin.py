from django.contrib import admin
from django.utils import timezone
from .models import Avatar, EmailAccount, SystemConfig, CompanyConfig, UserEmailToken

# Register your models here.

admin.site.register(Avatar)


class UserEmailTokenExpiredFilter(admin.SimpleListFilter):
	title = 'expired'
	parameter_name = 'expired'

	def lookups(self, request, model_admin):
		return (
			('yes', 'Yes'),
			('no', 'No'),
		)

	def queryset(self, request, queryset):
		now = timezone.now()
		value = self.value()
		if value == 'yes':
			return queryset.filter(expires_at__lte=now)
		if value == 'no':
			return queryset.filter(expires_at__gt=now)
		return queryset


@admin.register(EmailAccount)
class EmailAccountAdmin(admin.ModelAdmin):
	list_display = ('name', 'from_email', 'smtp_host', 'smtp_port', 'use_tls', 'use_ssl', 'is_active')
	list_filter = ('is_active', 'use_tls', 'use_ssl')
	search_fields = ('name', 'from_email', 'smtp_host')


@admin.register(SystemConfig)
class SystemConfigAdmin(admin.ModelAdmin):
	list_display = ('public_base_url', 'default_from_email', 'is_active')
	list_filter = ('is_active',)
	search_fields = ('public_base_url', 'default_from_email')


@admin.register(CompanyConfig)
class CompanyConfigAdmin(admin.ModelAdmin):
	list_display = ('empresa', 'public_base_url', 'from_email', 'from_name')
	search_fields = ('empresa__codigo', 'empresa__descripcion', 'from_email', 'from_name')


@admin.register(UserEmailToken)
class UserEmailTokenAdmin(admin.ModelAdmin):
	list_display = ('user', 'purpose', 'expires_at', 'used_at', 'created_at')
	list_filter = ('purpose', 'used_at', UserEmailTokenExpiredFilter)
	search_fields = ('user__username', 'user__email', 'token_hash')

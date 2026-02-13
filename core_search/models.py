from django.core.validators import RegexValidator
from django.db import models


class SearchPageIndex(models.Model):
    key = models.CharField(
        max_length=120,
        unique=True,
        validators=[RegexValidator(r"^[a-z0-9_.-]+$")],
    )

    vista = models.ForeignKey(
        "access_control.Vista",
        on_delete=models.CASCADE,
        related_name="search_pages",
    )

    url_name = models.CharField(max_length=200)
    url_kwargs_json = models.JSONField(default=dict, blank=True)

    label_key = models.CharField(max_length=200)
    default_label = models.CharField(max_length=200)
    group_key = models.CharField(max_length=200, blank=True, default="")

    keywords = models.TextField(blank=True, default="")
    order = models.IntegerField(default=100)
    is_active = models.BooleanField(default=True)

    class Meta:
        indexes = [
            models.Index(fields=["is_active", "order"]),
            models.Index(fields=["key"]),
        ]

    def __str__(self):
        return f"{self.key} -> {self.default_label}"

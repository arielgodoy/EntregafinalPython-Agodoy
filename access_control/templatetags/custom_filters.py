from django import template

register = template.Library()

@register.filter
def getattr(value, arg):
    """Obtiene el atributo 'arg' de un objeto."""
    return getattr(value, arg, None)

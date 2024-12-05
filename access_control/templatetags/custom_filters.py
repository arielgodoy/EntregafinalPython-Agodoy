from django import template

register = template.Library()

@register.filter
def getattr(obj, attr_name):
    """
    Obtiene el atributo `attr_name` del objeto `obj`.
    """
    try:
        return getattr(obj, attr_name, None)  # Nota: No hay recursión aquí
    except AttributeError:
        return None

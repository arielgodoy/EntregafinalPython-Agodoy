from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from .models import Tarea, TareaDocumento, DocumentoRequeridoTipoTarea


@receiver(pre_save, sender=Tarea)
def tarea_pre_save(sender, instance, **kwargs):
    """
    Signal pre-guardado para detectar cambios en tipo_tarea
    y limpiar documentos si es necesario
    """
    try:
        old_instance = Tarea.objects.get(pk=instance.pk)
        # Si tipo_tarea cambió, guardar el tipo anterior
        if old_instance.tipo_tarea_id != instance.tipo_tarea_id:
            instance._tipo_tarea_changed = True
            instance._old_tipo_tarea_id = old_instance.tipo_tarea_id
        else:
            instance._tipo_tarea_changed = False
    except Tarea.DoesNotExist:
        instance._tipo_tarea_changed = False


@receiver(post_save, sender=Tarea)
def auto_generar_documentos_tarea(sender, instance, created, **kwargs):
    """
    Signal que crea automáticamente TareaDocumento cuando:
    1. Se crea una nueva Tarea con tipo_tarea asignado
    2. Se cambia el tipo_tarea de una Tarea existente
    """
    if not instance.tipo_tarea:
        return
    
    # Si es creación o tipo_tarea cambió
    if created or getattr(instance, '_tipo_tarea_changed', False):
        # Si tipo_tarea cambió, eliminar documentos antiguos
        if not created and getattr(instance, '_tipo_tarea_changed', False):
            # Eliminar documentos del tipo anterior que no están aprobados/entregados
            old_tipo_tarea_id = getattr(instance, '_old_tipo_tarea_id', None)
            if old_tipo_tarea_id:
                TareaDocumento.objects.filter(
                    tarea=instance,
                    estado__in=['PENDIENTE', 'ENVIADO', 'RECIBIDO']
                ).delete()
        
        # Obtener documentos requeridos para este tipo de tarea
        documentos_requeridos = DocumentoRequeridoTipoTarea.objects.filter(
            tipo_tarea=instance.tipo_tarea
        ).order_by('orden')
        
        # Crear TareaDocumento para cada documento requerido
        for doc_req in documentos_requeridos:
            # Verificar si ya existe
            existe = TareaDocumento.objects.filter(
                tarea=instance,
                nombre_documento=doc_req.nombre_documento
            ).exists()
            
            if not existe:
                TareaDocumento.objects.create(
                    tarea=instance,
                    nombre_documento=doc_req.nombre_documento,
                    descripcion=doc_req.descripcion,
                    tipo_doc=doc_req.tipo_doc,
                    es_obligatorio=doc_req.es_obligatorio,
                    categoria=doc_req.categoria,
                    estado='PENDIENTE'
                )


def ready():
    """
    Esta función se llama cuando la app está lista.
    Se define en apps.py para registrar los signals.
    """
    import control_de_proyectos.signals  # noqa

from django.db import models
from django.contrib.auth.models import User

from django.contrib.auth.models import AbstractUser, Group, Permission
from django.db.models.signals import post_save
from django.dispatch import receiver
from settings.models import UserPreferences



# class CustomUser(AbstractUser):     
#      groups = models.ManyToManyField(Group, related_name='custom_users')
#      user_permissions = models.ManyToManyField(Permission, related_name='custom_users')    
#      def save(self, *args, **kwargs):
#         created = not self.pk  # Verificar si es un nuevo usuario
#         super().save(*args, **kwargs)
#         if created:
#             Avatar.objects.create(user=self)  # Crear un objeto Avatar para el nuevo usuario


class Avatar(models.Model):
    user = models.OneToOneField(User,on_delete=models.CASCADE,null=True)
    imagen = models.ImageField(default='default.jpg',upload_to='avatares',null = True, blank=True)    
    username = models.CharField(max_length=100,default='')
    first_name = models.CharField(max_length=100,default='')
    last_name = models.CharField(max_length=100,default='')
    email = models.EmailField(max_length=100,default='')
    profesion = models.CharField(max_length=100,default='')
    dni = models.CharField(max_length=20,default='')   
    def __str__(self):
        return f'{self.user} {self.imagen}'
    
@receiver(post_save, sender=User)
def create_user_avatar(sender, instance, created, **kwargs):
    if created:
        Avatar.objects.create(user=instance)
        UserPreferences.objects.create(user=instance)

    


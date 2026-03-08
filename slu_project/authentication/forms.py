from .models import user
from django import forms

class userform(forms.ModelForm):
    class Meta:
        model = user
        fields = ['username', 'password']
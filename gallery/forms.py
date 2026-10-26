from django import forms

from .models import Event


class EventForm(forms.ModelForm):
    class Meta:
        model = Event
        fields = ["name", "date"]
        widgets = {
            "name": forms.TextInput(attrs={"placeholder": "Priya & Arjun's Wedding"}),
            "date": forms.DateInput(attrs={"type": "date"}),
        }


class SelfieForm(forms.Form):
    selfie = forms.ImageField()

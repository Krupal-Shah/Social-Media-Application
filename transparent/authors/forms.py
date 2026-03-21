from django import forms
from django.contrib.auth.forms import UserCreationForm
from .models import Author


class RegisterForm(UserCreationForm):
    display_name = forms.CharField(
        max_length=255,
        required=True,
        widget=forms.TextInput(attrs={"placeholder": "Display name"}),
    )
    email = forms.EmailField(
        required=False,
        widget=forms.EmailInput(attrs={"placeholder": "Email (optional)"}),
    )
    github = forms.URLField(
        required=False,
        widget=forms.URLInput(
            attrs={"placeholder": "GitHub profile URL (optional)"}),
    )

    class Meta:
        model = Author
        fields = ("username", "display_name", "email",
                  "github", "password1", "password2")

    def save(self, commit=True):
        user = super().save(commit=False)
        user.display_name = self.cleaned_data["display_name"]
        user.email = self.cleaned_data.get("email", "")
        user.github = self.cleaned_data.get("github", "")
        user.approved = False 
        if commit:
            user.save()
        return user

class ProfileEditForm(forms.ModelForm):
    """
    Allow an author to update their public profile fields via the browser.
    """
    class Meta:
        model = Author
        fields = ("display_name", "description", "profile_image", "github")
        widgets = {
            "display_name": forms.TextInput(attrs={"placeholder": "Display name"}),
            "description": forms.Textarea(attrs={"rows": 4, "placeholder": "Write a short bio"}),
            "profile_image": forms.URLInput(attrs={"placeholder": "https://example.com/me.jpg"}),
            "github": forms.URLInput(attrs={"placeholder": "https://github.com/username"}),
        }
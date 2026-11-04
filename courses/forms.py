from django import forms

from .models import CourseReview


class CourseReviewForm(forms.ModelForm):
    class Meta:
        model = CourseReview
        fields = ("difficulty_rating", "workload_rating", "content")
        widgets = {
            "difficulty_rating": forms.NumberInput(attrs={"min": 1, "max": 5}),
            "workload_rating": forms.NumberInput(attrs={"min": 1, "max": 5}),
            "content": forms.Textarea(attrs={"rows": 5}),
        }

    def clean_difficulty_rating(self):
        return self._validate_rating("difficulty_rating")

    def clean_workload_rating(self):
        return self._validate_rating("workload_rating")

    def _validate_rating(self, field_name):
        rating = self.cleaned_data[field_name]
        if not 1 <= rating <= 5:
            raise forms.ValidationError("คะแนนต้องอยู่ระหว่าง 1 ถึง 5")
        return rating

    def clean_content(self):
        content = self.cleaned_data["content"].strip()
        if not content:
            raise forms.ValidationError("กรุณาเขียนข้อความรีวิว")
        return content

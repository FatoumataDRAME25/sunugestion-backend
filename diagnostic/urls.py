from django.urls import path
from .views import DiagnosticAPIView, AssistantChatAPIView

urlpatterns = [
    path('', DiagnosticAPIView.as_view(), name='diagnostic'),
    path('assistant/', AssistantChatAPIView.as_view(), name='assistant-chat'),
]
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenRefreshView

from apps.accounts import services
from apps.accounts.serializers import (
    LoginSerializer,
    RefreshTokenSerializer,
    SignupSerializer,
    TokenPairSerializer,
    UserSerializer,
)


class SignupView(APIView):
    authentication_classes: list = []
    permission_classes = [AllowAny]
    throttle_scope = "signup"

    @extend_schema(tags=["auth"], request=SignupSerializer, responses={201: UserSerializer})
    def post(self, request):
        serializer = SignupSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = services.register_user(**serializer.validated_data)
        return Response(UserSerializer(user).data, status=status.HTTP_201_CREATED)


class LoginView(APIView):
    authentication_classes: list = []
    permission_classes = [AllowAny]
    throttle_scope = "login"

    @extend_schema(tags=["auth"], request=LoginSerializer, responses={200: TokenPairSerializer})
    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user, refresh = services.login(request=request, **serializer.validated_data)
        body = {"access": str(refresh.access_token), "refresh": str(refresh), "user": user}
        return Response(TokenPairSerializer(body).data)


class RefreshView(TokenRefreshView):
    """Exchange a refresh token for a new pair; the old refresh token is blacklisted."""

    authentication_classes: list = []
    throttle_scope = "login"


class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(tags=["auth"], request=RefreshTokenSerializer, responses={204: None})
    def post(self, request):
        serializer = RefreshTokenSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.logout(user=request.user, refresh_token=serializer.validated_data["refresh"])
        return Response(status=status.HTTP_204_NO_CONTENT)


class MeView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(tags=["auth"], responses={200: UserSerializer})
    def get(self, request):
        return Response(UserSerializer(request.user).data)

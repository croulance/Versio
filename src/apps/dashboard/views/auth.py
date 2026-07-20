from django.shortcuts import redirect, render
from django.views import View

from apps.dashboard import auth_client


class LoginView(View):
    def get(self, request):
        if request.session.get("token"):
            return redirect("/")
        return render(request, "dashboard/login.html", {})

    def post(self, request):
        email = request.POST.get("email", "").strip()
        password = request.POST.get("password", "")

        result = auth_client.login(email, password)
        if result:
            request.session["token"] = result["token"]
            return redirect("/")

        return render(
            request,
            "dashboard/login.html",
            {
                "error": "Invalid email or password.",
                "email": email,
            },
        )


class LogoutView(View):
    def post(self, request):
        request.session.flush()
        return redirect("/login/")

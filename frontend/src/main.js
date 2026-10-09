import { initializeAuth } from "./auth.js";
import { mountDashboard } from "./dashboardUI.js";

const loginView = document.querySelector("#login-view");
const dashboardView = document.querySelector("#dashboard-view");
let dashboardSession = null;
let dashboardUI = null;
let transitionTimer = null;

const auth = initializeAuth({ onAuthenticated: showDashboard });

function showDashboard(user, session) {
  if (dashboardSession?.user?.id === user.id) return;
  dashboardSession = session || { user, demo: true };
  document.querySelector("#intro-video").pause();
  window.clearTimeout(transitionTimer);
  loginView.classList.add("is-transitioning");
  window.setTimeout(() => {
    loginView.hidden = true;
    dashboardView.hidden = false;
    dashboardView.classList.remove("is-transitioning");
    dashboardUI?.destroy();
    dashboardUI = mountDashboard({
      user,
      session: dashboardSession,
      onLogout: returnToLogin,
    });
  }, 240);
}

function returnToLogin() {
  dashboardUI?.destroy();
  dashboardUI = null;
  dashboardSession = null;
  dashboardView.classList.add("is-transitioning");
  window.setTimeout(() => {
    dashboardView.hidden = true;
    dashboardView.classList.remove("is-transitioning");
    loginView.hidden = false;
    loginView.classList.remove("is-transitioning");
    auth.logout();
  }, 200);
}

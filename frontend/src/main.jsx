import { lazy, StrictMode, Suspense } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import { CssBaseline, ThemeProvider } from "@mui/material";
import "@fontsource/roboto/400.css";
import "@fontsource/roboto/500.css";
import "@fontsource/roboto/600.css";
import "@fontsource/roboto/700.css";
import { AuthProvider, RequireAuth } from "./auth";
import AppShell from "./components/AppShell";
import FullPageSpinner from "./components/FullPageSpinner";
import { NotifyProvider } from "./notify";
import theme from "./theme";

// Each page is its own chunk, so guests' phones don't download the photographer screens.
const Dashboard = lazy(() => import("./pages/Dashboard"));
const EventDetail = lazy(() => import("./pages/EventDetail"));
const GuestEvent = lazy(() => import("./pages/GuestEvent"));
const GuestResults = lazy(() => import("./pages/GuestResults"));
const Login = lazy(() => import("./pages/Login"));
const NotFound = lazy(() => import("./pages/NotFound"));
const Poster = lazy(() => import("./pages/Poster"));

createRoot(document.getElementById("root")).render(
  <StrictMode>
    <ThemeProvider theme={theme}>
      <CssBaseline />
      <NotifyProvider>
        <BrowserRouter>
          <AuthProvider>
            <Suspense fallback={<FullPageSpinner />}>
            <Routes>
              {/* Guests (from the QR code): no account, no app bar */}
              <Route path="/e/:slug/" element={<GuestEvent />} />
              <Route path="/e/:slug/my-photos/" element={<GuestResults />} />
              <Route path="/events/:slug/poster/" element={<RequireAuth><Poster /></RequireAuth>} />

              {/* Photographers */}
              <Route element={<AppShell />}>
                <Route path="/login/" element={<Login />} />
                <Route path="/" element={<RequireAuth><Dashboard /></RequireAuth>} />
                <Route path="/events/:slug/" element={<RequireAuth><EventDetail /></RequireAuth>} />
                <Route path="*" element={<NotFound />} />
              </Route>
            </Routes>
            </Suspense>
          </AuthProvider>
        </BrowserRouter>
      </NotifyProvider>
    </ThemeProvider>
  </StrictMode>,
);

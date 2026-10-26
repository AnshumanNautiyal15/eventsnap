import { AppBar, Box, Button, Container, IconButton, Toolbar, Tooltip, Typography } from "@mui/material";
import CameraAltOutlinedIcon from "@mui/icons-material/CameraAltOutlined";
import AdminPanelSettingsOutlinedIcon from "@mui/icons-material/AdminPanelSettingsOutlined";
import LogoutIcon from "@mui/icons-material/Logout";
import { Link as RouterLink, Outlet, useNavigate } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";

// Layout for photographer pages: top app bar + centred content.
export default function AppShell() {
  const { user, setUser } = useAuth();
  const navigate = useNavigate();

  const logout = async () => {
    await api("/api/auth/logout/", { method: "POST" });
    setUser(null);
    navigate("/login/");
  };

  return (
    <Box sx={{ minHeight: "100vh", bgcolor: "background.default" }}>
      <AppBar position="sticky" color="inherit" elevation={0} sx={{ borderBottom: 1, borderColor: "divider" }}>
        <Toolbar>
          <Button
            component={RouterLink}
            to="/"
            color="inherit"
            startIcon={<CameraAltOutlinedIcon color="primary" />}
            sx={{ fontFamily: "Georgia, serif", fontSize: "1.25rem", fontWeight: 500 }}
          >
            WeddingSnap
          </Button>
          <Box sx={{ flexGrow: 1 }} />
          {user ? (
            <>
              {user.is_admin && (
                <Button href="/admin/" startIcon={<AdminPanelSettingsOutlinedIcon />} sx={{ mr: 1 }}>
                  Admin
                </Button>
              )}
              <Typography variant="body2" color="text.secondary" sx={{ mr: 1, display: { xs: "none", sm: "block" } }}>
                {user.username}
              </Typography>
              <Tooltip title="Log out">
                <IconButton onClick={logout} aria-label="Log out">
                  <LogoutIcon />
                </IconButton>
              </Tooltip>
            </>
          ) : (
            <Button component={RouterLink} to="/login/">
              Log in
            </Button>
          )}
        </Toolbar>
      </AppBar>
      <Container maxWidth="lg" sx={{ py: { xs: 3, md: 4 } }}>
        <Outlet />
      </Container>
    </Box>
  );
}

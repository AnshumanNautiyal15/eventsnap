import { useState } from "react";
import { Alert, Box, Button, Card, CardContent, Stack, TextField, Typography } from "@mui/material";
import { Navigate, useNavigate, useSearchParams } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";

export default function Login() {
  const { user, setUser } = useAuth();
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const [form, setForm] = useState({ username: "", password: "" });
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const next = params.get("next");

  if (user) return <Navigate to="/" replace />;

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const data = await api("/api/auth/login/", { method: "POST", json: form });
      setUser(data.user);
      // `next` can be a server URL (e.g. the Google connect link), so do a real navigation for it.
      if (next && next.startsWith("/") && !next.startsWith("//")) window.location.assign(next);
      else navigate("/");
    } catch (err) {
      setError(err.message);
      setBusy(false);
    }
  };

  const set = (field) => (e) => setForm({ ...form, [field]: e.target.value });

  return (
    <Box sx={{ maxWidth: 420, mx: "auto", mt: { xs: 2, md: 6 } }}>
      <Card>
        <CardContent sx={{ p: { xs: 3, sm: 4 } }}>
          <Typography variant="h4" component="h1" gutterBottom>
            Photographer log in
          </Typography>
          <Typography color="text.secondary" sx={{ mb: 3 }}>
            Manage your events, upload photos and print QR codes.
          </Typography>
          <Stack component="form" spacing={2} onSubmit={submit}>
            {error && <Alert severity="error">{error}</Alert>}
            <TextField label="Username" value={form.username} onChange={set("username")} autoComplete="username" autoFocus required />
            <TextField label="Password" type="password" value={form.password} onChange={set("password")} autoComplete="current-password" required />
            <Button type="submit" variant="contained" size="large" loading={busy}>
              Log in
            </Button>
          </Stack>
          <Typography variant="body2" color="text.secondary" sx={{ mt: 3 }}>
            Accounts are created by the WeddingSnap admin. Contact them for a login or more storage.
          </Typography>
        </CardContent>
      </Card>
    </Box>
  );
}

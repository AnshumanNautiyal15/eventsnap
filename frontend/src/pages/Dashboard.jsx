import { useEffect, useState } from "react";
import {
  Alert, Box, Button, Card, CardContent, CardHeader, Chip, Grid, List, ListItemButton, ListItemText,
  Skeleton, Stack, TextField, Typography,
} from "@mui/material";
import AddIcon from "@mui/icons-material/Add";
import EventOutlinedIcon from "@mui/icons-material/EventOutlined";
import { Link as RouterLink, useNavigate } from "react-router-dom";
import { api } from "../api";
import StorageMeter from "../components/StorageMeter";
import { formatDate } from "../format";

export default function Dashboard() {
  const navigate = useNavigate();
  const [events, setEvents] = useState(null);
  const [storage, setStorage] = useState(null);
  const [loadError, setLoadError] = useState("");
  const [form, setForm] = useState({ name: "", date: "" });
  const [errors, setErrors] = useState({});
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api("/api/events/")
      .then((d) => {
        setEvents(d.events);
        setStorage(d.storage);
      })
      .catch((e) => setLoadError(e.message));
  }, []);

  const create = async (e) => {
    e.preventDefault();
    setBusy(true);
    try {
      const { slug } = await api("/api/events/", { method: "POST", json: { name: form.name, date: form.date || null } });
      navigate(`/events/${slug}/`);
    } catch (err) {
      setErrors(err.data?.errors || { name: [err.message] });
      setBusy(false);
    }
  };

  return (
    <>
      <Typography variant="h4" component="h1">
        Your events
      </Typography>
      <Typography color="text.secondary" sx={{ mb: 3 }}>
        Create an event, upload its photos, and put the QR code up at the venue.
      </Typography>

      <Grid container spacing={3}>
        <Grid size={{ xs: 12, md: 7 }}>
          <Card>
            <CardHeader title="Events" slotProps={{ title: { variant: "h6" } }} />
            {loadError && <Alert severity="error" sx={{ mx: 2, mb: 2 }}>{loadError}</Alert>}
            {events === null && !loadError ? (
              <Box sx={{ px: 2, pb: 2 }}>
                {[0, 1, 2].map((i) => <Skeleton key={i} height={56} />)}
              </Box>
            ) : events?.length === 0 ? (
              <CardContent sx={{ textAlign: "center", color: "text.secondary" }}>
                <EventOutlinedIcon sx={{ fontSize: 48, opacity: 0.4 }} />
                <Typography>No events yet. Create your first one.</Typography>
              </CardContent>
            ) : (
              <List disablePadding>
                {events?.map((e) => (
                  <ListItemButton key={e.slug} component={RouterLink} to={`/events/${e.slug}/`} divider>
                    <ListItemText
                      primary={e.name}
                      secondary={`${e.date ? formatDate(e.date) : "No date"} · ${e.indexed}/${e.photos} photos indexed`}
                      slotProps={{ primary: { fontWeight: 500 } }}
                    />
                    <Chip
                      size="small"
                      label={e.is_active ? "Live" : "Closed"}
                      color={e.is_active ? "success" : "default"}
                      variant={e.is_active ? "filled" : "outlined"}
                      sx={{ ml: 1 }}
                    />
                  </ListItemButton>
                ))}
              </List>
            )}
          </Card>
        </Grid>

        <Grid size={{ xs: 12, md: 5 }}>
          <Card sx={{ mb: 3 }}>
            <CardHeader title="Storage" slotProps={{ title: { variant: "h6" } }} />
            <CardContent sx={{ pt: 0 }}>
              {storage ? <StorageMeter storage={storage} /> : <Skeleton height={40} />}
              <Typography variant="caption" color="text.secondary" sx={{ display: "block", mt: 1 }}>
                Uploaded photos and their previews count towards this. Removing photos or deleting events frees it again.
              </Typography>
            </CardContent>
          </Card>
          <Card>
            <CardHeader title="New event" slotProps={{ title: { variant: "h6" } }} />
            <CardContent sx={{ pt: 0 }}>
              <Stack component="form" spacing={2} onSubmit={create}>
                <TextField
                  label="Event name"
                  placeholder="Priya & Arjun's Wedding"
                  value={form.name}
                  onChange={(e) => setForm({ ...form, name: e.target.value })}
                  error={!!errors.name}
                  helperText={errors.name?.join(" ")}
                  required
                />
                <TextField
                  label="Date"
                  type="date"
                  value={form.date}
                  onChange={(e) => setForm({ ...form, date: e.target.value })}
                  error={!!errors.date}
                  helperText={errors.date?.join(" ")}
                  slotProps={{ inputLabel: { shrink: true } }}
                />
                <Button type="submit" variant="contained" startIcon={<AddIcon />} loading={busy} sx={{ alignSelf: "flex-start" }}>
                  Create event
                </Button>
              </Stack>
            </CardContent>
          </Card>
        </Grid>
      </Grid>
    </>
  );
}

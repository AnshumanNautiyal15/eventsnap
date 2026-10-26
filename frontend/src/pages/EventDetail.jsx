import { useCallback, useEffect, useRef, useState } from "react";
import {
  Alert, Box, Button, Chip, FormControlLabel, Grid, IconButton, ListItemIcon, Menu, MenuItem, Stack, Switch, Tooltip,
  Typography,
} from "@mui/material";
import ArrowBackIcon from "@mui/icons-material/ArrowBack";
import DeleteForeverOutlinedIcon from "@mui/icons-material/DeleteForeverOutlined";
import DeleteSweepOutlinedIcon from "@mui/icons-material/DeleteSweepOutlined";
import MoreVertIcon from "@mui/icons-material/MoreVert";
import { Link as RouterLink, useParams, useSearchParams } from "react-router-dom";
import { api } from "../api";
import FullPageSpinner from "../components/FullPageSpinner";
import DeleteEventDialog from "../components/event/DeleteEventDialog";
import DriveCard from "../components/event/DriveCard";
import NoFaceDialog from "../components/event/NoFaceDialog";
import ProcessingCard from "../components/event/ProcessingCard";
import QrCard from "../components/event/QrCard";
import RecentPhotos from "../components/event/RecentPhotos";
import UploadCard from "../components/event/UploadCard";
import { formatDate } from "../format";
import { useNotify } from "../notify";

const POLL_MS = 2000;
const RECENT_REFRESH_MS = 6000;

export default function EventDetail() {
  const { slug } = useParams();
  const notify = useNotify();
  const [params, setParams] = useSearchParams();
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [stats, setStats] = useState(null);
  const [syncing, setSyncing] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [startingIndex, setStartingIndex] = useState(false);
  const [menuAnchor, setMenuAnchor] = useState(null);
  const [dialog, setDialog] = useState(null); // "delete" | "no-faces"
  const last = useRef({ syncing: false, done: 0, refreshedAt: 0 });

  const load = useCallback(async () => {
    try {
      const d = await api(`/api/events/${slug}/`);
      setData(d);
      setStats(d.stats);
      setSyncing(d.drive.syncing);
      last.current = { syncing: d.drive.syncing, done: d.stats.done, refreshedAt: Date.now() };
    } catch (e) {
      setError(e);
    }
  }, [slug]);

  useEffect(() => {
    load();
  }, [load]);

  // Result of the Google sign-in round trip comes back as ?drive=connected / ?drive_error=...
  useEffect(() => {
    if (params.get("drive") === "connected") notify("Google Drive connected.");
    if (params.get("drive_error")) notify(params.get("drive_error"), "error");
    if (params.has("drive") || params.has("drive_error")) setParams({}, { replace: true });
  }, [params, setParams, notify]);

  // Poll progress while anything is running; refresh the full page data when work finishes.
  const busy = uploading || syncing || (stats?.queued ?? 0) > 0;
  useEffect(() => {
    if (!busy) return undefined;
    const timer = setInterval(async () => {
      const s = await api(`/api/events/${slug}/status/`).catch(() => null);
      if (!s) return;
      setStats(s);
      setSyncing(s.drive_syncing);
      const prev = last.current;
      const syncFinished = prev.syncing && !s.drive_syncing;
      const newPhotos = s.done !== prev.done && Date.now() - prev.refreshedAt > RECENT_REFRESH_MS;
      const queueEmptied = s.queued === 0 && s.done !== prev.done;
      last.current = { ...prev, syncing: s.drive_syncing };
      if (syncFinished || newPhotos || queueEmptied) load();
    }, POLL_MS);
    return () => clearInterval(timer);
  }, [busy, slug, load]);

  const toggle = async () => {
    const { is_active } = await api(`/api/events/${slug}/toggle/`, { method: "POST" });
    setData((d) => ({ ...d, event: { ...d.event, is_active } }));
    notify(is_active ? "Guests can search for their photos again." : "Photo search is now closed to guests.", "info");
  };

  const startIndexing = async () => {
    setStartingIndex(true);
    try {
      const r = await api(`/api/events/${slug}/index/`, { method: "POST" });
      notify(r.message, r.queued ? "info" : "success");
      setStats((s) => ({ ...s, pending: 0, queued: r.queued }));
    } catch (err) {
      notify(err.message, "error");
    }
    setStartingIndex(false);
  };

  const retry = async () => {
    const { message } = await api(`/api/events/${slug}/reprocess/`, { method: "POST" });
    notify(message, "info");
    await load();
    setStats((s) => ({ ...s, queued: Math.max(s.queued, 1) })); // start polling right away
  };

  if (error) {
    return (
      <Alert severity="error" action={<Button component={RouterLink} to="/" color="inherit">All events</Button>}>
        {error.status === 404 ? "Event not found." : error.message}
      </Alert>
    );
  }
  if (!data) return <FullPageSpinner />;

  const { event, drive, recent } = data;
  const driveEnabled = drive.enabled && (drive.public_configured || drive.oauth_configured);

  return (
    <>
      <Button component={RouterLink} to="/" startIcon={<ArrowBackIcon />} size="small" sx={{ mb: 1 }}>
        All events
      </Button>
      <Stack direction={{ xs: "column", sm: "row" }} spacing={2} sx={{ justifyContent: "space-between", alignItems: { sm: "center" }, mb: 3 }}>
        <Box>
          <Typography variant="h4" component="h1">{event.name}</Typography>
          <Stack direction="row" spacing={1} sx={{ alignItems: "center", mt: 0.5 }}>
            {event.date && <Typography color="text.secondary">{formatDate(event.date)}</Typography>}
            <Chip
              size="small"
              label={event.is_active ? "Live for guests" : "Closed to guests"}
              color={event.is_active ? "success" : "default"}
              variant={event.is_active ? "filled" : "outlined"}
            />
          </Stack>
        </Box>
        <Stack direction="row" sx={{ alignItems: "center" }}>
          <FormControlLabel control={<Switch checked={event.is_active} onChange={toggle} />} label="Guests can search" />
          <Tooltip title="More">
            <IconButton onClick={(e) => setMenuAnchor(e.currentTarget)} aria-label="More event actions">
              <MoreVertIcon />
            </IconButton>
          </Tooltip>
        </Stack>
      </Stack>

      <Menu anchorEl={menuAnchor} open={!!menuAnchor} onClose={() => setMenuAnchor(null)}
        anchorOrigin={{ vertical: "bottom", horizontal: "right" }} transformOrigin={{ vertical: "top", horizontal: "right" }}>
        <MenuItem onClick={() => { setMenuAnchor(null); setDialog("no-faces"); }} disabled={!stats.no_faces}>
          <ListItemIcon><DeleteSweepOutlinedIcon fontSize="small" /></ListItemIcon>
          Remove photos with no faces{stats.no_faces ? ` (${stats.no_faces})` : ""}
        </MenuItem>
        <MenuItem onClick={() => { setMenuAnchor(null); setDialog("delete"); }} sx={{ color: "error.main" }}>
          <ListItemIcon><DeleteForeverOutlinedIcon fontSize="small" color="error" /></ListItemIcon>
          Delete event
        </MenuItem>
      </Menu>
      <DeleteEventDialog event={event} open={dialog === "delete"} onClose={() => setDialog(null)} />
      <NoFaceDialog slug={slug} open={dialog === "no-faces"} onClose={() => setDialog(null)} onRemoved={load} />

      <Grid container spacing={3}>
        <Grid size={{ xs: 12, md: 6 }}>
          <QrCard event={event} />
        </Grid>
        <Grid size={{ xs: 12, md: 6 }}>
          <ProcessingCard stats={stats} onIndex={startIndexing} indexing={startingIndex} onRetry={retry}
            onReviewNoFaces={() => setDialog("no-faces")} />
        </Grid>
        {driveEnabled && (
        <Grid size={{ xs: 12, md: 6 }}>
          <DriveCard
            slug={slug}
            drive={drive}
            syncing={syncing}
            onChange={load}
            onSyncStarted={() => { setSyncing(true); last.current.syncing = true; }}
          />
        </Grid>
        )}
        <Grid size={{ xs: 12, md: driveEnabled ? 6 : 12 }}>
          <UploadCard
            slug={slug}
            folder={event.folder}
            storage={data.storage}
            title={driveEnabled ? "Or upload photos" : "Add photos"}
            onUploading={(on) => { setUploading(on); if (!on) load(); }}
            onScanned={load}
          />
        </Grid>
        <Grid size={12}>
          <RecentPhotos photos={recent} />
        </Grid>
      </Grid>
    </>
  );
}

import { useEffect, useMemo, useState } from "react";
import {
  Alert, Box, Button, Checkbox, CircularProgress, Dialog, DialogActions, DialogContent, DialogTitle, ImageList,
  ImageListItem, Stack, Typography, useMediaQuery,
} from "@mui/material";
import { useTheme } from "@mui/material/styles";
import DeleteSweepOutlinedIcon from "@mui/icons-material/DeleteSweepOutlined";
import { api } from "../../api";
import { formatBytes, plural } from "../../format";
import { useNotify } from "../../notify";

// Review the photos where no faces were found, untick any to keep, and remove the rest.
export default function NoFaceDialog({ slug, open, onClose, onRemoved }) {
  const notify = useNotify();
  const theme = useTheme();
  const fullScreen = useMediaQuery(theme.breakpoints.down("sm"));
  const sm = useMediaQuery(theme.breakpoints.up("sm"));
  const [photos, setPhotos] = useState(null);
  const [selected, setSelected] = useState(new Set());
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!open) return;
    setPhotos(null);
    api(`/api/events/${slug}/no-face-photos/`).then(({ photos: list }) => {
      setPhotos(list);
      setSelected(new Set(list.map((p) => p.id)));
    });
  }, [open, slug]);

  const chosen = useMemo(() => (photos || []).filter((p) => selected.has(p.id)), [photos, selected]);
  const freed = chosen.reduce((sum, p) => sum + p.bytes, 0);
  const anyDrive = chosen.some((p) => p.from_drive);

  const toggle = (id) => setSelected((prev) => {
    const next = new Set(prev);
    next.has(id) ? next.delete(id) : next.add(id);
    return next;
  });

  const remove = async () => {
    setBusy(true);
    try {
      const { message } = await api(`/api/events/${slug}/remove-photos/`, { method: "POST", json: { ids: chosen.map((p) => p.id) } });
      notify(message);
      onRemoved();
      onClose();
    } catch (err) {
      notify(err.message, "error");
    }
    setBusy(false);
  };

  return (
    <Dialog open={open} onClose={busy ? undefined : onClose} fullScreen={fullScreen} maxWidth="md" fullWidth>
      <DialogTitle>Photos with no faces</DialogTitle>
      <DialogContent dividers>
        {photos === null ? (
          <Box sx={{ display: "grid", placeItems: "center", py: 6 }}><CircularProgress /></Box>
        ) : photos.length === 0 ? (
          <Typography color="text.secondary">Every photo has at least one face.</Typography>
        ) : (
          <Stack spacing={2}>
            <Typography color="text.secondary">
              Guests search by face, so they can never find these photos. Removing them frees storage. Untick any you want
              to keep in the event.
            </Typography>
            <Stack direction="row" spacing={1}>
              <Button size="small" onClick={() => setSelected(new Set(photos.map((p) => p.id)))}>Select all</Button>
              <Button size="small" onClick={() => setSelected(new Set())}>Select none</Button>
            </Stack>
            <ImageList cols={sm ? 5 : 3} gap={8} sx={{ m: 0 }}>
              {photos.map((p) => {
                const on = selected.has(p.id);
                return (
                  <ImageListItem key={p.id} onClick={() => toggle(p.id)}
                    sx={{ cursor: "pointer", aspectRatio: "1", borderRadius: 2, overflow: "hidden", bgcolor: "divider",
                      outline: on ? `3px solid ${theme.palette.error.main}` : "none", outlineOffset: -3 }}>
                    {p.thumb && <img src={p.thumb} alt={p.name} loading="lazy"
                      style={{ width: "100%", height: "100%", objectFit: "cover", opacity: on ? 0.75 : 1 }} />}
                    <Checkbox checked={on} color="error" size="small" tabIndex={-1}
                      sx={{ position: "absolute", top: 2, left: 2, bgcolor: "rgba(255,255,255,.85)", p: 0.25, borderRadius: 1, "&:hover": { bgcolor: "#fff" } }}
                      slotProps={{ input: { "aria-label": `Remove ${p.name}` } }} />
                  </ImageListItem>
                );
              })}
            </ImageList>
            {anyDrive && (
              <Alert severity="info">
                Photos from Google Drive stay in your Drive; they're only removed from this event and won't come back on the next sync.
              </Alert>
            )}
          </Stack>
        )}
      </DialogContent>
      <DialogActions sx={{ px: 3, py: 2 }}>
        <Typography variant="body2" color="text.secondary" sx={{ flexGrow: 1 }}>
          {chosen.length ? `${plural(chosen.length, "photo")} · frees ${formatBytes(freed)}` : ""}
        </Typography>
        <Button onClick={onClose} disabled={busy}>Cancel</Button>
        <Button variant="contained" color="error" startIcon={<DeleteSweepOutlinedIcon />} onClick={remove}
          disabled={!chosen.length} loading={busy}>
          Remove {chosen.length || ""}
        </Button>
      </DialogActions>
    </Dialog>
  );
}

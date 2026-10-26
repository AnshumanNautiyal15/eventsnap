import { useState } from "react";
import { Alert, Button, Dialog, DialogActions, DialogContent, DialogTitle, Stack, TextField, Typography } from "@mui/material";
import DeleteForeverOutlinedIcon from "@mui/icons-material/DeleteForeverOutlined";
import { useNavigate } from "react-router-dom";
import { api } from "../../api";
import { useNotify } from "../../notify";

export default function DeleteEventDialog({ event, open, onClose }) {
  const notify = useNotify();
  const navigate = useNavigate();
  const [typed, setTyped] = useState("");
  const [busy, setBusy] = useState(false);
  const matches = typed.trim() === event.name.trim();

  const remove = async () => {
    setBusy(true);
    try {
      const { message } = await api(`/api/events/${event.slug}/delete/`, { method: "POST" });
      notify(message, "info");
      navigate("/", { replace: true });
    } catch (err) {
      notify(err.message, "error");
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onClose={busy ? undefined : onClose} maxWidth="xs" fullWidth>
      <DialogTitle>Delete this event?</DialogTitle>
      <DialogContent>
        <Stack spacing={2}>
          <Alert severity="warning">
            This permanently deletes the event, every photo uploaded to it and all previews, and frees that storage.
            The QR code stops working for guests.
          </Alert>
          <Typography variant="body2">
            Type <b>{event.name}</b> to confirm.
          </Typography>
          <TextField size="small" value={typed} onChange={(e) => setTyped(e.target.value)} autoFocus
            placeholder={event.name} onKeyDown={(e) => e.key === "Enter" && matches && remove()} />
        </Stack>
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 2 }}>
        <Button onClick={onClose} disabled={busy}>Cancel</Button>
        <Button variant="contained" color="error" startIcon={<DeleteForeverOutlinedIcon />} disabled={!matches}
          loading={busy} onClick={remove}>
          Delete event
        </Button>
      </DialogActions>
    </Dialog>
  );
}

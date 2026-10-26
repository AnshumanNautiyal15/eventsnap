import { useState } from "react";
import {
  Accordion, AccordionDetails, AccordionSummary, Alert, Box, Button, Card, CardContent, CardHeader, Chip, Dialog,
  DialogActions, DialogContent, DialogContentText, DialogTitle, LinearProgress, Link, Stack, TextField, Typography,
} from "@mui/material";
import AddLinkIcon from "@mui/icons-material/AddLink";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import FolderIcon from "@mui/icons-material/Folder";
import GoogleIcon from "@mui/icons-material/Google";
import LinkOffIcon from "@mui/icons-material/LinkOff";
import SyncIcon from "@mui/icons-material/Sync";
import { useLocation } from "react-router-dom";
import { api } from "../../api";
import { plural, timeAgo } from "../../format";
import { useNotify } from "../../notify";

function LinkFolderForm({ slug, drive, onLinked }) {
  const notify = useNotify();
  const [link, setLink] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const { message } = await api(`/api/events/${slug}/drive/folder/`, { method: "POST", json: { folder_link: link } });
      notify(message);
      setLink("");
      onLinked();
    } catch (err) {
      setError(err.message);
    }
    setBusy(false);
  };

  return (
    <Stack spacing={1.5}>
      <Stack component="form" direction={{ xs: "column", sm: "row" }} spacing={1} onSubmit={submit}>
        <TextField
          size="small"
          label="Google Drive folder link"
          placeholder="https://drive.google.com/drive/folders/…"
          value={link}
          onChange={(e) => setLink(e.target.value)}
          error={!!error}
          required
        />
        <Button type="submit" variant="contained" startIcon={<AddLinkIcon />} loading={busy} sx={{ flexShrink: 0 }}>
          Link folder
        </Button>
      </Stack>
      {error && <Alert severity="error">{error}</Alert>}
      {drive.public_configured && (
        <Typography variant="body2" color="text.secondary">
          In Drive: right-click the folder → <b>Share</b> → General access: <b>Anyone with the link</b> (Viewer) →{" "}
          <b>Copy link</b>. Every subfolder is included.
        </Typography>
      )}
    </Stack>
  );
}

function AccountRow({ drive, onChange }) {
  const notify = useNotify();
  const location = useLocation();
  if (!drive.oauth_configured) return null;

  const disconnect = async () => {
    const { message } = await api("/api/google/disconnect/", { method: "POST" });
    notify(message, "info");
    onChange();
  };

  return drive.connected ? (
    <Stack direction="row" spacing={1} sx={{ alignItems: "center", flexWrap: "wrap" }}>
      <GoogleIcon fontSize="small" color="action" />
      <Typography variant="body2" color="text.secondary">
        Private folders are read with <b>{drive.account_email || "your Google account"}</b>.
      </Typography>
      <Button size="small" onClick={disconnect}>
        Disconnect
      </Button>
    </Stack>
  ) : (
    <Stack direction={{ xs: "column", sm: "row" }} spacing={1} sx={{ alignItems: { sm: "center" } }}>
      <Typography variant="body2" color="text.secondary">
        {drive.public_configured ? "Folder must stay private?" : "Connect Google Drive to link a folder."}
      </Typography>
      <Button
        size="small"
        variant={drive.public_configured ? "text" : "contained"}
        startIcon={<GoogleIcon />}
        href={`${drive.connect_url}?next=${encodeURIComponent(location.pathname)}`}
      >
        Connect your Google account
      </Button>
    </Stack>
  );
}

export default function DriveCard({ slug, drive, syncing, onChange, onSyncStarted }) {
  const notify = useNotify();
  const location = useLocation();
  const [confirmUnlink, setConfirmUnlink] = useState(false);

  if (!drive.public_configured && !drive.oauth_configured) {
    return (
      <Card>
        <CardHeader title="Google Drive" slotProps={{ title: { variant: "h6" } }} />
        <CardContent sx={{ pt: 0 }}>
          <Alert severity="info">
            Google Drive isn't set up on this server yet. Add <code>GOOGLE_API_KEY</code> to <code>.env</code> (see README) and
            restart.
          </Alert>
        </CardContent>
      </Card>
    );
  }

  const sync = async () => {
    const { started } = await api(`/api/events/${slug}/drive/sync/`, { method: "POST" });
    if (started) onSyncStarted();
  };

  const unlink = async () => {
    setConfirmUnlink(false);
    const { message } = await api(`/api/events/${slug}/drive/unlink/`, { method: "POST" });
    notify(message, "info");
    onChange();
  };

  const linked = !!drive.folder_id;

  return (
    <Card>
      <CardHeader title="Google Drive" slotProps={{ title: { variant: "h6" } }} />
      <CardContent sx={{ pt: 0 }}>
        {linked ? (
          <Stack spacing={2}>
            <Stack direction="row" spacing={1} useFlexGap sx={{ alignItems: "center", flexWrap: "wrap" }}>
              <FolderIcon color="primary" />
              <Link href={`https://drive.google.com/drive/folders/${drive.folder_id}`} target="_blank" rel="noopener" variant="subtitle1" sx={{ fontWeight: 600 }}>
                {drive.folder_name}
              </Link>
              <Chip size="small" label="All subfolders" variant="outlined" />
              {drive.access && <Chip size="small" label={drive.access} variant="outlined" />}
            </Stack>

            <Box>
              {syncing ? (
                <>
                  <LinearProgress sx={{ borderRadius: 4, mb: 1 }} />
                  <Typography variant="body2" color="text.secondary">Reading the folder and its subfolders…</Typography>
                </>
              ) : (
                <Typography variant="body2" color="text.secondary">
                  {drive.synced_at ? `Last synced ${timeAgo(drive.synced_at)}.` : "Not synced yet."} New photos added to
                  Drive are picked up every few minutes; press Index photos to make them searchable.
                </Typography>
              )}
              {drive.video_count > 0 && (
                <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
                  {plural(drive.video_count, "video")} in the folder {drive.video_count === 1 ? "isn't" : "aren't"} searched (photos only).
                </Typography>
              )}
            </Box>

            {drive.error && !syncing && (
              <Alert
                severity="error"
                action={drive.needs_reconnect && (
                  <Button color="inherit" size="small" startIcon={<GoogleIcon />} href={`${drive.connect_url}?next=${encodeURIComponent(location.pathname)}`}>
                    Reconnect
                  </Button>
                )}
              >
                {drive.error}
              </Alert>
            )}

            <Stack direction="row" spacing={1}>
              <Button variant="contained" startIcon={<SyncIcon />} onClick={sync} disabled={syncing}>
                {syncing ? "Syncing…" : "Sync now"}
              </Button>
              <Button variant="outlined" color="inherit" startIcon={<LinkOffIcon />} onClick={() => setConfirmUnlink(true)}>
                Unlink
              </Button>
            </Stack>

            <Accordion disableGutters elevation={0} sx={{ border: 1, borderColor: "divider", borderRadius: 2, "&::before": { display: "none" } }}>
              <AccordionSummary expandIcon={<ExpandMoreIcon />}>
                <Typography variant="body2">Use a different folder</Typography>
              </AccordionSummary>
              <AccordionDetails>
                <Stack spacing={2}>
                  <LinkFolderForm slug={slug} drive={drive} onLinked={onChange} />
                  <AccountRow drive={drive} onChange={onChange} />
                </Stack>
              </AccordionDetails>
            </Accordion>
          </Stack>
        ) : (
          <Stack spacing={2}>
            <Typography color="text.secondary">
              Keep the photos in Google Drive. Paste the event's folder link and every photo in it, including subfolders,
              becomes searchable.
            </Typography>
            {(drive.public_configured || drive.connected) && <LinkFolderForm slug={slug} drive={drive} onLinked={onChange} />}
            <AccountRow drive={drive} onChange={onChange} />
          </Stack>
        )}
      </CardContent>

      <Dialog open={confirmUnlink} onClose={() => setConfirmUnlink(false)}>
        <DialogTitle>Unlink this folder?</DialogTitle>
        <DialogContent>
          <DialogContentText>
            Its photos are removed from this event and guests can no longer find them. Nothing in your Google Drive is
            changed or deleted.
          </DialogContentText>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setConfirmUnlink(false)}>Cancel</Button>
          <Button color="error" onClick={unlink}>Unlink</Button>
        </DialogActions>
      </Dialog>
    </Card>
  );
}

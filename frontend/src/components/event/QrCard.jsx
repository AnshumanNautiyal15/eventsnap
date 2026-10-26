import { Box, Button, Card, CardContent, CardHeader, IconButton, InputAdornment, Stack, TextField, Tooltip, Typography } from "@mui/material";
import ContentCopyIcon from "@mui/icons-material/ContentCopy";
import DownloadIcon from "@mui/icons-material/Download";
import OpenInNewIcon from "@mui/icons-material/OpenInNew";
import PrintIcon from "@mui/icons-material/Print";
import { Link as RouterLink } from "react-router-dom";
import { useNotify } from "../../notify";

async function copyText(text) {
  if (navigator.clipboard && window.isSecureContext) return navigator.clipboard.writeText(text);
  // Clipboard API needs https/localhost; fall back for plain-http LAN addresses.
  const area = Object.assign(document.createElement("textarea"), { value: text });
  document.body.appendChild(area);
  area.select();
  document.execCommand("copy");
  area.remove();
}

export default function QrCard({ event }) {
  const notify = useNotify();

  const copy = async () => {
    await copyText(event.guest_url);
    notify("Guest link copied.");
  };

  return (
    <Card sx={{ height: "100%" }}>
      <CardHeader title="Guest QR code" slotProps={{ title: { variant: "h6" } }} />
      <CardContent sx={{ pt: 0 }}>
        <Stack direction={{ xs: "column", sm: "row" }} spacing={3}>
          <Box
            component="img"
            src={event.qr_url}
            alt="QR code for guests"
            sx={{ width: 190, height: 190, borderRadius: 2, border: 1, borderColor: "divider", alignSelf: { xs: "center", sm: "flex-start" } }}
          />
          <Stack spacing={2} sx={{ flex: 1, minWidth: 0 }}>
            <Typography variant="body2" color="text.secondary">
              Guests scan this, take a selfie, and get only the photos they're in.
            </Typography>
            <TextField
              size="small"
              label="Guest link"
              value={event.guest_url}
              slotProps={{
                input: {
                  readOnly: true,
                  endAdornment: (
                    <InputAdornment position="end">
                      <Tooltip title="Copy link">
                        <IconButton onClick={copy} edge="end" aria-label="Copy guest link">
                          <ContentCopyIcon fontSize="small" />
                        </IconButton>
                      </Tooltip>
                    </InputAdornment>
                  ),
                },
              }}
            />
            <Stack direction="row" spacing={1} useFlexGap sx={{ flexWrap: "wrap" }}>
              <Button variant="contained" startIcon={<PrintIcon />} component={RouterLink} to={`/events/${event.slug}/poster/`} target="_blank">
                Print poster
              </Button>
              <Button variant="outlined" startIcon={<DownloadIcon />} href={`${event.qr_url}?download=1`}>
                PNG
              </Button>
              <Button startIcon={<OpenInNewIcon />} href={event.guest_url} target="_blank" rel="noopener">
                Guest page
              </Button>
            </Stack>
          </Stack>
        </Stack>
      </CardContent>
    </Card>
  );
}

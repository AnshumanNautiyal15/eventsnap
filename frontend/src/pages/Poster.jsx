import { useEffect, useState } from "react";
import { Alert, Box, Button, Typography } from "@mui/material";
import PrintIcon from "@mui/icons-material/Print";
import { useParams } from "react-router-dom";
import { api } from "../api";
import FullPageSpinner from "../components/FullPageSpinner";

// Printable A4 sign for the venue.
export default function Poster() {
  const { slug } = useParams();
  const [event, setEvent] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api(`/api/events/${slug}/`).then((d) => setEvent(d.event)).catch((e) => setError(e.message));
  }, [slug]);

  if (error) return <Alert severity="error" sx={{ m: 3 }}>{error}</Alert>;
  if (!event) return <FullPageSpinner />;

  return (
    <Box sx={{ textAlign: "center", py: 6, px: 2, bgcolor: "#fff", minHeight: "100vh" }}>
      <Button variant="contained" startIcon={<PrintIcon />} onClick={() => window.print()} sx={{ mb: 4, displayPrint: "none" }}>
        Print
      </Button>
      <Typography variant="overline" color="text.secondary" sx={{ display: "block", fontSize: "1rem" }}>
        {event.name}
      </Typography>
      <Typography variant="h3" component="h1" sx={{ fontSize: { xs: "2.4rem", sm: "3.4rem" }, mb: 2 }}>
        Find your photos
      </Typography>
      <Typography sx={{ fontSize: "1.25rem", mb: 4 }}>Scan, take a selfie, and get every photo you're in.</Typography>
      <Box component="img" src={event.qr_url} alt="QR code" sx={{ width: 380, maxWidth: "80vw" }} />
      <Typography variant="body2" color="text.secondary" sx={{ mt: 2 }}>{event.guest_url}</Typography>
    </Box>
  );
}

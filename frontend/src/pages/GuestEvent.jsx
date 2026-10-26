import { useEffect, useRef, useState } from "react";
import { Alert, Avatar, Box, Button, Card, CardContent, CircularProgress, Stack, Typography } from "@mui/material";
import FaceRetouchingNaturalIcon from "@mui/icons-material/FaceRetouchingNatural";
import PhotoCameraIcon from "@mui/icons-material/PhotoCamera";
import PhotoLibraryOutlinedIcon from "@mui/icons-material/PhotoLibraryOutlined";
import LockOutlinedIcon from "@mui/icons-material/LockOutlined";
import { useNavigate, useParams } from "react-router-dom";
import { api } from "../api";
import FullPageSpinner from "../components/FullPageSpinner";
import GuestLayout from "../components/GuestLayout";

// Shrink the selfie on the phone before upload: faster on venue Wi-Fi, same match quality.
function shrink(file, maxSide = 1280) {
  return new Promise((resolve) => {
    const img = new Image();
    img.onload = () => {
      const scale = Math.min(1, maxSide / Math.max(img.width, img.height));
      const canvas = document.createElement("canvas");
      canvas.width = Math.round(img.width * scale);
      canvas.height = Math.round(img.height * scale);
      canvas.getContext("2d").drawImage(img, 0, 0, canvas.width, canvas.height);
      canvas.toBlob((blob) => resolve(blob || file), "image/jpeg", 0.9);
    };
    img.onerror = () => resolve(file); // e.g. HEIC on some browsers: let the server decode it
    img.src = URL.createObjectURL(file);
  });
}

export default function GuestEvent() {
  const { slug } = useParams();
  const navigate = useNavigate();
  const input = useRef(null);
  const [event, setEvent] = useState(null);
  const [notFound, setNotFound] = useState(false);
  const [preview, setPreview] = useState(null);
  const [searching, setSearching] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    api(`/api/e/${slug}/`).then(setEvent).catch(() => setNotFound(true));
  }, [slug]);

  const pick = (useCamera) => {
    if (useCamera) input.current.setAttribute("capture", "user");
    else input.current.removeAttribute("capture");
    input.current.click();
  };

  const search = async (file) => {
    if (!file) return;
    setPreview(URL.createObjectURL(file));
    setError("");
    setSearching(true);
    try {
      const form = new FormData();
      form.append("selfie", await shrink(file), "selfie.jpg");
      await api(`/api/e/${slug}/search/`, { method: "POST", form });
      navigate(`/e/${slug}/my-photos/`);
    } catch (err) {
      setError(err.message);
      setSearching(false);
    }
  };

  if (notFound) {
    return (
      <GuestLayout eyebrow="WeddingSnap" title="Event not found">
        <Typography align="center" color="text.secondary">Please check the link or scan the QR code again.</Typography>
      </GuestLayout>
    );
  }
  if (!event) return <FullPageSpinner />;

  return (
    <GuestLayout eyebrow="Find your photos" title={event.name} date={event.date}>
      <Card sx={{ borderRadius: 4 }}>
        <CardContent sx={{ p: { xs: 3, sm: 4 }, textAlign: "center" }}>
          {!event.is_active ? (
            <Stack spacing={1} sx={{ alignItems: "center" }}>
              <LockOutlinedIcon color="action" sx={{ fontSize: 48 }} />
              <Typography variant="h6">Photo search is closed</Typography>
              <Typography color="text.secondary">Please contact the photographer for your photos.</Typography>
            </Stack>
          ) : event.indexed === 0 ? (
            <Stack spacing={1} sx={{ alignItems: "center" }}>
              <PhotoLibraryOutlinedIcon color="action" sx={{ fontSize: 48 }} />
              <Typography variant="h6">Photos are on their way</Typography>
              <Typography color="text.secondary">The photographer hasn't added photos yet. Please check back later!</Typography>
            </Stack>
          ) : (
            <Stack spacing={2.5} sx={{ alignItems: "center" }}>
              <Avatar
                src={preview || undefined}
                sx={{ width: 168, height: 168, bgcolor: "#f1e6d8", color: "primary.main", border: "4px solid #fff", boxShadow: 3 }}
              >
                <FaceRetouchingNaturalIcon sx={{ fontSize: 80 }} />
              </Avatar>
              {error && <Alert severity="warning" sx={{ width: "100%", textAlign: "left" }}>{error}</Alert>}
              {searching ? (
                <Stack spacing={1.5} sx={{ alignItems: "center", py: 1 }}>
                  <CircularProgress />
                  <Typography color="text.secondary">Searching {event.indexed} photos…</Typography>
                </Stack>
              ) : (
                <>
                  <Typography sx={{ fontSize: "1.1rem" }}>
                    Take a quick selfie and we'll find every photo you're in.
                  </Typography>
                  <Button variant="contained" size="large" fullWidth startIcon={<PhotoCameraIcon />} onClick={() => pick(true)} sx={{ py: 1.6, fontSize: "1.05rem" }}>
                    {error ? "Try another selfie" : "Take a selfie"}
                  </Button>
                  <Button onClick={() => pick(false)}>or choose an existing photo</Button>
                </>
              )}
              <input ref={input} type="file" accept="image/*" hidden onChange={(e) => { search(e.target.files[0]); e.target.value = ""; }} />
            </Stack>
          )}
        </CardContent>
      </Card>
      <Box sx={{ textAlign: "center", mt: 2 }}>
        <Typography variant="caption" color="text.secondary">
          Your selfie is only used to find your photos and is never stored.
        </Typography>
      </Box>
    </GuestLayout>
  );
}

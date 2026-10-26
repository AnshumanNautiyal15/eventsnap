import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Box, Button, Dialog, IconButton, ImageList, ImageListItem, Stack, Typography, useMediaQuery,
} from "@mui/material";
import { useTheme } from "@mui/material/styles";
import ChevronLeftIcon from "@mui/icons-material/ChevronLeft";
import ChevronRightIcon from "@mui/icons-material/ChevronRight";
import CloseIcon from "@mui/icons-material/Close";
import DownloadIcon from "@mui/icons-material/Download";
import FaceIcon from "@mui/icons-material/Face";
import SearchOffIcon from "@mui/icons-material/SearchOff";
import { Link as RouterLink, useNavigate, useParams } from "react-router-dom";
import { api } from "../api";
import FullPageSpinner from "../components/FullPageSpinner";
import GuestLayout from "../components/GuestLayout";
import { plural } from "../format";

function Viewer({ photos, index, onClose, onMove }) {
  const theme = useTheme();
  const fullScreen = useMediaQuery(theme.breakpoints.down("sm"));
  const photo = index === null ? null : photos[index];
  const [touchX, setTouchX] = useState(null);

  useEffect(() => {
    if (index === null) return undefined;
    const onKey = (e) => {
      if (e.key === "ArrowLeft") onMove(-1);
      if (e.key === "ArrowRight") onMove(1);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [index, onMove]);

  return (
    <Dialog
      open={!!photo}
      onClose={onClose}
      fullScreen={fullScreen}
      maxWidth="lg"
      slotProps={{ paper: { sx: { bgcolor: "#111", color: "#fff", m: { sm: 2 } } } }}
    >
      {photo && (
        <Box
          sx={{ position: "relative", display: "flex", flexDirection: "column", height: { xs: "100%", sm: "auto" } }}
          onTouchStart={(e) => setTouchX(e.touches[0].clientX)}
          onTouchEnd={(e) => {
            if (touchX === null) return;
            const dx = e.changedTouches[0].clientX - touchX;
            if (Math.abs(dx) > 50) onMove(dx < 0 ? 1 : -1); // swipe between photos
            setTouchX(null);
          }}
        >
          <Stack direction="row" sx={{ alignItems: "center", px: 1, py: 0.5 }}>
            <Typography variant="body2" sx={{ flexGrow: 1, pl: 1, opacity: 0.8 }}>
              {index + 1} / {photos.length}
            </Typography>
            <IconButton onClick={onClose} sx={{ color: "#fff" }} aria-label="Close">
              <CloseIcon />
            </IconButton>
          </Stack>
          <Box sx={{ flexGrow: 1, display: "flex", alignItems: "center", justifyContent: "center", position: "relative", minHeight: 0 }}>
            <Box
              component="img"
              src={photo.thumb}
              alt=""
              sx={{ maxWidth: "100%", maxHeight: { xs: "calc(100vh - 140px)", sm: "75vh" }, display: "block", userSelect: "none" }}
            />
            {index > 0 && (
              <IconButton onClick={() => onMove(-1)} aria-label="Previous photo"
                sx={{ position: "absolute", left: 8, bgcolor: "rgba(0,0,0,.4)", color: "#fff", "&:hover": { bgcolor: "rgba(0,0,0,.6)" } }}>
                <ChevronLeftIcon />
              </IconButton>
            )}
            {index < photos.length - 1 && (
              <IconButton onClick={() => onMove(1)} aria-label="Next photo"
                sx={{ position: "absolute", right: 8, bgcolor: "rgba(0,0,0,.4)", color: "#fff", "&:hover": { bgcolor: "rgba(0,0,0,.6)" } }}>
                <ChevronRightIcon />
              </IconButton>
            )}
          </Box>
          <Box sx={{ p: 2, textAlign: "center" }}>
            <Button variant="contained" startIcon={<DownloadIcon />} href={photo.download}>
              Download original
            </Button>
          </Box>
        </Box>
      )}
    </Dialog>
  );
}

export default function GuestResults() {
  const { slug } = useParams();
  const navigate = useNavigate();
  const theme = useTheme();
  const md = useMediaQuery(theme.breakpoints.up("md"));
  const sm = useMediaQuery(theme.breakpoints.up("sm"));
  const [data, setData] = useState(null);
  const [open, setOpen] = useState(null);

  useEffect(() => {
    api(`/api/e/${slug}/my-photos/`)
      .then(setData)
      .catch(() => navigate(`/e/${slug}/`, { replace: true })); // no selfie yet in this browser
  }, [slug, navigate]);

  const all = useMemo(() => (data ? data.sections.flatMap((s) => s.photos) : []), [data]);
  const move = useCallback((step) => setOpen((i) => (i === null ? i : Math.min(Math.max(i + step, 0), all.length - 1))), [all.length]);

  if (!data) return <FullPageSpinner />;

  let offset = 0;
  return (
    <GuestLayout eyebrow={data.event.name} maxWidth="lg">
      <Box sx={{ textAlign: "center", mt: -3, mb: 4 }}>
        {data.count ? (
          <>
            <FaceIcon color="primary" sx={{ fontSize: 40 }} />
            <Typography variant="h4" component="h1">
              We found {plural(data.count, "photo")} of you
            </Typography>
            <Stack direction="row" spacing={1.5} sx={{ justifyContent: "center", mt: 2.5, flexWrap: "wrap" }} useFlexGap>
              <Button variant="contained" size="large" startIcon={<DownloadIcon />} href={data.zip_url}>
                Download all
              </Button>
              <Button variant="outlined" size="large" component={RouterLink} to={`/e/${slug}/`}>
                Try another selfie
              </Button>
            </Stack>
          </>
        ) : (
          <Stack spacing={1.5} sx={{ alignItems: "center" }}>
            <SearchOffIcon color="action" sx={{ fontSize: 48 }} />
            <Typography variant="h4" component="h1">No photos found yet</Typography>
            <Typography color="text.secondary">
              The photographer may still be adding photos, or try a clearer selfie facing the camera.
            </Typography>
            <Button variant="contained" size="large" component={RouterLink} to={`/e/${slug}/`}>
              Try again
            </Button>
          </Stack>
        )}
      </Box>

      {data.sections.map((section) => {
        const start = offset;
        offset += section.photos.length;
        return (
          <Box key={section.folder || "_root"} sx={{ mb: 3 }}>
            {section.folder && (
              <Typography variant="h6" component="h2" sx={{ mb: 1.5 }}>
                {section.folder}
              </Typography>
            )}
            <ImageList cols={md ? 5 : sm ? 3 : 2} gap={8} sx={{ m: 0 }}>
              {section.photos.map((p, i) => (
                <ImageListItem
                  key={p.id}
                  onClick={() => setOpen(start + i)}
                  sx={{ cursor: "pointer", aspectRatio: "1", borderRadius: 2, overflow: "hidden", bgcolor: "divider" }}
                >
                  <img src={p.thumb} alt="" loading="lazy" style={{ width: "100%", height: "100%", objectFit: "cover" }} />
                </ImageListItem>
              ))}
            </ImageList>
          </Box>
        );
      })}

      <Viewer photos={all} index={open} onClose={() => setOpen(null)} onMove={move} />
    </GuestLayout>
  );
}

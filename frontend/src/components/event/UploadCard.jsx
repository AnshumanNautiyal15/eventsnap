import { useRef, useState } from "react";
import {
  Accordion, AccordionDetails, AccordionSummary, Box, Button, Card, CardContent, CardHeader, LinearProgress, Paper,
  Stack, Typography,
} from "@mui/material";
import CloudUploadOutlinedIcon from "@mui/icons-material/CloudUploadOutlined";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import FolderOpenIcon from "@mui/icons-material/FolderOpen";
import { api } from "../../api";
import { useNotify } from "../../notify";
import StorageMeter from "../StorageMeter";

const BATCH = 5; // files per request
const PARALLEL = 3; // requests at once
const IMAGE_NAME = /\.(jpe?g|jfif|png|webp|heic|heif|hif|avif|tiff?|bmp|gif|psd|cr2|cr3|crw|nef|nrw|arw|srf|sr2|dng|raf|orf|rw2|pef|srw|x3f|3fr|iiq|erf|kdc|dcr|rwl)$/i;

export default function UploadCard({ slug, folder, storage, title, onUploading, onScanned }) {
  const notify = useNotify();
  const input = useRef(null);
  const [over, setOver] = useState(false);
  const [progress, setProgress] = useState(null); // {done, failed, total}
  const [scanning, setScanning] = useState(false);

  const upload = async (fileList) => {
    const files = [...fileList].filter((f) => f.type.startsWith("image/") || IMAGE_NAME.test(f.name));
    if (!files.length) return;
    const batches = [];
    for (let i = 0; i < files.length; i += BATCH) batches.push(files.slice(i, i + BATCH));
    const state = { done: 0, failed: 0, total: files.length, full: "" };
    setProgress({ ...state });
    onUploading(true);

    const worker = async () => {
      while (batches.length) {
        const batch = batches.shift();
        const form = new FormData();
        batch.forEach((f) => form.append("photos", f));
        try {
          const r = await api(`/api/events/${slug}/upload/`, { method: "POST", form });
          state.done += r.added;
          state.failed += r.skipped + r.rejected;
          if (r.rejected) {
            state.full = r.error;
            state.failed += batches.flat().length; // storage is full: don't send the rest
            batches.length = 0;
          }
        } catch {
          state.failed += batch.length;
        }
        setProgress({ ...state });
      }
    };
    await Promise.all(Array.from({ length: PARALLEL }, worker));
    onUploading(false);
    if (state.full) notify(`Uploaded ${state.done} photos. ${state.full}`, "error");
    else notify(
      (state.failed ? `Uploaded ${state.done} photos, ${state.failed} failed.` : `Uploaded ${state.done} photos.`)
        + " Press Index photos when you're ready to make them searchable.",
      state.failed ? "warning" : "success",
    );
  };

  const scan = async () => {
    setScanning(true);
    try {
      const { message } = await api(`/api/events/${slug}/scan-folder/`, { method: "POST" });
      notify(message, "info");
      onScanned();
    } catch (err) {
      notify(err.message, "error");
    }
    setScanning(false);
  };

  const finished = progress ? progress.done + progress.failed : 0;

  return (
    <Card>
      <CardHeader title={title} slotProps={{ title: { variant: "h6" } }} />
      <CardContent sx={{ pt: 0 }}>
        <Box sx={{ mb: 2 }}>
          <StorageMeter storage={storage} compact />
        </Box>
        <Paper
          variant="outlined"
          role="button"
          tabIndex={0}
          onClick={() => input.current.click()}
          onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && input.current.click()}
          onDragOver={(e) => { e.preventDefault(); setOver(true); }}
          onDragLeave={() => setOver(false)}
          onDrop={(e) => { e.preventDefault(); setOver(false); upload(e.dataTransfer.files); }}
          sx={{
            p: 4, textAlign: "center", cursor: "pointer", borderStyle: "dashed", borderWidth: 2,
            borderColor: over ? "primary.main" : "divider", bgcolor: over ? "action.hover" : "transparent",
            transition: "all .2s",
          }}
        >
          <CloudUploadOutlinedIcon color="primary" sx={{ fontSize: 44 }} />
          <Typography variant="subtitle1" sx={{ fontWeight: 600 }}>Drop photos here or click to choose</Typography>
          <Typography variant="body2" color="text.secondary">
            JPEG, HEIC, RAW and more. Press Index photos afterwards to make them searchable.
          </Typography>
          <input ref={input} type="file" multiple accept="image/*,.cr2,.cr3,.nef,.arw,.dng,.raf,.orf,.rw2,.heic" hidden
            onChange={(e) => { upload(e.target.files); e.target.value = ""; }} />
        </Paper>

        {progress && (
          <Box sx={{ mt: 2 }}>
            <LinearProgress variant="determinate" value={(finished / progress.total) * 100} sx={{ height: 8, borderRadius: 4 }} />
            <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
              Uploaded {progress.done} of {progress.total}
              {progress.failed ? ` · ${progress.failed} failed` : ""}
              {finished === progress.total ? " · done" : "…"}
            </Typography>
          </Box>
        )}

        {folder && (
        <Accordion disableGutters elevation={0} sx={{ mt: 2, border: 1, borderColor: "divider", borderRadius: 2, "&::before": { display: "none" } }}>
          <AccordionSummary expandIcon={<ExpandMoreIcon />}>
            <Typography variant="body2">Copying a whole folder on the server instead?</Typography>
          </AccordionSummary>
          <AccordionDetails>
            <Stack spacing={1.5}>
              <Typography variant="body2" color="text.secondary">Copy the photos into this folder, then press Scan folder:</Typography>
              <Box component="code" sx={{ bgcolor: "background.default", p: 1, borderRadius: 1, wordBreak: "break-all", fontSize: 13 }}>
                {folder}
              </Box>
              <Typography variant="body2" color="text.secondary">
                Or from a terminal: <code>python manage.py import_photos {slug} /path/to/photos</code>
              </Typography>
              <Button variant="outlined" startIcon={<FolderOpenIcon />} onClick={scan} loading={scanning} sx={{ alignSelf: "flex-start" }}>
                Scan folder
              </Button>
            </Stack>
          </AccordionDetails>
        </Accordion>
        )}
      </CardContent>
    </Card>
  );
}

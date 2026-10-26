import { Alert, Box, Button, Card, CardContent, CardHeader, Grid, LinearProgress, Typography } from "@mui/material";
import DeleteSweepOutlinedIcon from "@mui/icons-material/DeleteSweepOutlined";
import FaceRetouchingNaturalIcon from "@mui/icons-material/FaceRetouchingNatural";
import { plural } from "../../format";

function Stat({ value, label }) {
  return (
    <Box sx={{ bgcolor: "background.default", borderRadius: 2, py: 1.5, textAlign: "center" }}>
      <Typography variant="h5" component="div" sx={{ fontFamily: "Roboto, sans-serif", fontWeight: 600 }}>
        {value}
      </Typography>
      <Typography variant="caption" color="text.secondary">
        {label}
      </Typography>
    </Box>
  );
}

export default function ProcessingCard({ stats, onIndex, indexing, onRetry, onReviewNoFaces }) {
  const finished = stats.done + stats.failed + stats.storage_blocked;
  const progress = stats.total ? (finished / stats.total) * 100 : 0;
  const running = stats.queued > 0;

  return (
    <Card sx={{ height: "100%" }}>
      <CardHeader title="Processing" slotProps={{ title: { variant: "h6" } }} />
      <CardContent sx={{ pt: 0 }}>
        <Grid container spacing={1.5} sx={{ mb: 2 }}>
          <Grid size={{ xs: 6, sm: 3 }}><Stat value={stats.total} label="Photos" /></Grid>
          <Grid size={{ xs: 6, sm: 3 }}><Stat value={stats.done} label="Indexed" /></Grid>
          <Grid size={{ xs: 6, sm: 3 }}><Stat value={stats.pending + stats.queued} label="Not indexed" /></Grid>
          <Grid size={{ xs: 6, sm: 3 }}><Stat value={stats.faces} label="Faces" /></Grid>
        </Grid>
        <LinearProgress variant={running ? "buffer" : "determinate"} value={progress} valueBuffer={progress}
          sx={{ height: 8, borderRadius: 4 }} />
        <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
          {stats.total === 0
            ? "No photos yet. Upload them below."
            : running
              ? `Finding faces… ${plural(stats.queued, "photo")} to go. Photos become searchable as each one finishes.`
              : stats.pending
                ? `${plural(stats.pending, "photo")} ${stats.pending === 1 ? "isn't" : "aren't"} indexed yet, so guests can't find ${stats.pending === 1 ? "it" : "them"}.`
                : "All photos are searchable."}
        </Typography>
        {stats.pending > 0 && !running && (
          <Button variant="contained" size="large" startIcon={<FaceRetouchingNaturalIcon />} onClick={onIndex}
            loading={indexing} sx={{ mt: 2 }}>
            Index {plural(stats.pending, "photo")}
          </Button>
        )}
        {stats.storage_blocked > 0 && (
          <Alert
            severity="error"
            sx={{ mt: 2 }}
            action={<Button color="inherit" size="small" onClick={onRetry}>Retry</Button>}
          >
            Storage is full: {plural(stats.storage_blocked, "photo")} couldn't be added. Ask the admin
            for more storage, then press Retry.
          </Alert>
        )}
        {stats.no_faces > 0 && (
          <Alert
            severity="info"
            icon={<DeleteSweepOutlinedIcon />}
            sx={{ mt: 2 }}
            action={<Button color="inherit" size="small" onClick={onReviewNoFaces}>Review</Button>}
          >
            {plural(stats.no_faces, "photo")} {stats.no_faces === 1 ? "has" : "have"} no faces, so guests can't find{" "}
            {stats.no_faces === 1 ? "it" : "them"}. Remove to free storage.
          </Alert>
        )}
        {stats.failed > 0 && (
          <Alert
            severity="warning"
            sx={{ mt: 2 }}
            action={<Button color="inherit" size="small" onClick={onRetry}>Retry</Button>}
          >
            {plural(stats.failed, "photo")} couldn't be read.
          </Alert>
        )}
      </CardContent>
    </Card>
  );
}

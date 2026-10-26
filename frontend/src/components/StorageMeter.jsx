import { Box, LinearProgress, Stack, Typography } from "@mui/material";
import { formatBytes } from "../format";

// "1.2 GB of 5 GB used" with a bar; admins have no limit.
export default function StorageMeter({ storage, compact = false }) {
  if (!storage) return null;
  const { used, limit } = storage;
  if (limit === null) {
    return <Typography variant="body2" color="text.secondary">{formatBytes(used)} used · unlimited (admin)</Typography>;
  }
  const pct = limit ? Math.min(100, (used / limit) * 100) : 100;
  const color = pct >= 95 ? "error" : pct >= 80 ? "warning" : "primary";
  return (
    <Box>
      <Stack direction="row" sx={{ justifyContent: "space-between", mb: 0.5 }}>
        <Typography variant="body2" sx={{ fontWeight: 500 }}>
          {formatBytes(used)} of {formatBytes(limit)} used
        </Typography>
        {!compact && <Typography variant="body2" color="text.secondary">{Math.round(pct)}%</Typography>}
      </Stack>
      <LinearProgress variant="determinate" value={pct} color={color} sx={{ height: compact ? 6 : 8, borderRadius: 4 }} />
      {!compact && pct >= 80 && (
        <Typography variant="caption" color={pct >= 95 ? "error" : "text.secondary"} sx={{ display: "block", mt: 0.5 }}>
          {pct >= 100 ? "Storage is full. " : "Running low. "}Ask the admin for more storage.
        </Typography>
      )}
    </Box>
  );
}

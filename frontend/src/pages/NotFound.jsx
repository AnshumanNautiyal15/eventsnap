import { Button, Stack, Typography } from "@mui/material";
import { Link as RouterLink } from "react-router-dom";

export default function NotFound() {
  return (
    <Stack spacing={2} sx={{ alignItems: "center", textAlign: "center", py: 10 }}>
      <Typography variant="h3" component="h1">Page not found</Typography>
      <Typography color="text.secondary">If you scanned a QR code, please scan it again.</Typography>
      <Button variant="contained" component={RouterLink} to="/">Go home</Button>
    </Stack>
  );
}

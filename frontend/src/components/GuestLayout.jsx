import { Box, Container, Typography } from "@mui/material";
import { formatDate } from "../format";

// Mobile-first layout for the pages guests reach from the QR code.
export default function GuestLayout({ eyebrow, title, date, children, maxWidth = "sm" }) {
  return (
    <Box
      sx={{
        minHeight: "100vh",
        background: "linear-gradient(180deg, #f3e9dc 0%, #faf7f2 320px)",
        pb: 6,
      }}
    >
      <Container maxWidth={maxWidth}>
        <Box sx={{ textAlign: "center", pt: { xs: 5, sm: 7 }, pb: 3 }}>
          {eyebrow && (
            <Typography variant="overline" color="primary">
              {eyebrow}
            </Typography>
          )}
          {title && (
            <Typography variant="h3" component="h1" sx={{ fontSize: { xs: "2.1rem", sm: "2.8rem" } }}>
              {title}
            </Typography>
          )}
          {date && (
            <Typography color="text.secondary" sx={{ mt: 1 }}>
              {formatDate(date)}
            </Typography>
          )}
        </Box>
        {children}
      </Container>
    </Box>
  );
}

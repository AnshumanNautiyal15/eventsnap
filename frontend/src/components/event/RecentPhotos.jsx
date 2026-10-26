import { Box, Card, CardContent, CardHeader, ImageList, ImageListItem, ImageListItemBar, Tooltip, useMediaQuery } from "@mui/material";
import { useTheme } from "@mui/material/styles";
import HourglassEmptyIcon from "@mui/icons-material/HourglassEmpty";
import ErrorOutlineIcon from "@mui/icons-material/ErrorOutlineOutlined";
import { plural } from "../../format";

function label(p) {
  const source = p.from_drive ? "Drive · " : "";
  if (p.status === "done") return source + plural(p.face_count, "face");
  return source + p.status_label;
}

export default function RecentPhotos({ photos }) {
  const theme = useTheme();
  const md = useMediaQuery(theme.breakpoints.up("md"));
  const sm = useMediaQuery(theme.breakpoints.up("sm"));
  const cols = md ? 6 : sm ? 4 : 3;
  if (!photos.length) return null;

  return (
    <Card>
      <CardHeader title="Recently added" slotProps={{ title: { variant: "h6" } }} />
      <CardContent sx={{ pt: 0 }}>
        <ImageList cols={cols} gap={8} sx={{ m: 0 }}>
          {photos.map((p) => (
            <ImageListItem
              key={p.id}
              component="a"
              href={p.full}
              target="_blank"
              rel="noopener"
              sx={{ aspectRatio: "1", borderRadius: 2, overflow: "hidden", bgcolor: "divider" }}
            >
              {p.thumb ? (
                <img src={p.thumb} alt={p.name} loading="lazy" style={{ width: "100%", height: "100%", objectFit: "cover" }} />
              ) : (
                <Tooltip title={p.error || p.name}>
                  <Box sx={{ height: "100%", display: "grid", placeItems: "center", color: "text.secondary" }}>
                    {p.status === "failed" ? <ErrorOutlineIcon color="warning" /> : <HourglassEmptyIcon />}
                  </Box>
                </Tooltip>
              )}
              <ImageListItemBar subtitle={label(p)} sx={{ background: "linear-gradient(transparent, rgba(0,0,0,.6))" }} />
            </ImageListItem>
          ))}
        </ImageList>
      </CardContent>
    </Card>
  );
}

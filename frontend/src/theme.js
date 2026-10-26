import { createTheme } from "@mui/material/styles";

const serif = 'Georgia, "Times New Roman", serif';

// Material Design with a warm, wedding-friendly palette and serif headings.
const theme = createTheme({
  palette: {
    primary: { main: "#7b4f2c" },
    secondary: { main: "#3e6259" },
    background: { default: "#faf7f2", paper: "#ffffff" },
  },
  shape: { borderRadius: 12 },
  typography: {
    fontFamily: 'Roboto, "Helvetica Neue", Arial, sans-serif',
    h3: { fontFamily: serif, fontWeight: 500 },
    h4: { fontFamily: serif, fontWeight: 500 },
    h5: { fontFamily: serif, fontWeight: 500 },
    h6: { fontWeight: 500 },
    button: { textTransform: "none", fontWeight: 600 },
    overline: { letterSpacing: "0.2em" },
  },
  components: {
    MuiButton: { defaultProps: { disableElevation: true }, styleOverrides: { root: { borderRadius: 999 } } },
    MuiCard: { defaultProps: { variant: "outlined" } },
    MuiTextField: { defaultProps: { fullWidth: true } },
    MuiChip: { styleOverrides: { root: { fontWeight: 500 } } },
  },
});

export default theme;

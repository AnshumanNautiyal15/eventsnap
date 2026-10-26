import { createContext, useCallback, useContext, useState } from "react";
import { Alert, Snackbar } from "@mui/material";

const NotifyContext = createContext(() => {});

// App-wide toast messages: const notify = useNotify(); notify("Saved"); notify("Oops", "error");
export function NotifyProvider({ children }) {
  const [message, setMessage] = useState({ text: "", severity: "success", key: 0 });
  const [open, setOpen] = useState(false);

  const notify = useCallback((text, severity = "success") => {
    setMessage({ text, severity, key: Date.now() });
    setOpen(true);
  }, []);

  const close = (_, reason) => reason !== "clickaway" && setOpen(false);

  return (
    <NotifyContext.Provider value={notify}>
      {children}
      <Snackbar
        key={message.key}
        open={open}
        autoHideDuration={message.severity === "error" ? 10000 : 5000}
        onClose={close}
        anchorOrigin={{ vertical: "bottom", horizontal: "center" }}
      >
        <Alert severity={message.severity} variant="filled" onClose={close} sx={{ width: "100%" }}>
          {message.text}
        </Alert>
      </Snackbar>
    </NotifyContext.Provider>
  );
}

export const useNotify = () => useContext(NotifyContext);

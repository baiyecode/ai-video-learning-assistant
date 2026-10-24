import * as Sentry from "@sentry/vue";
import { createPinia } from "pinia";
import { createApp } from "vue";

import App from "@/App.vue";
import { router } from "@/router";
import { useAuthStore } from "@/stores/auth";
import "@/style.css";

const app = createApp(App);
const pinia = createPinia();

const sentryDsn = import.meta.env.VITE_SENTRY_DSN;
if (sentryDsn) {
  Sentry.init({
    app,
    dsn: sentryDsn,
    environment: import.meta.env.MODE,
    sendDefaultPii: false,
  });
}

app.use(pinia);
// Restore the Session from the HttpOnly refresh cookie; the router guard awaits the result.
void useAuthStore(pinia).bootstrap();
app.use(router);
app.mount("#app");

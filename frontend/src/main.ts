import { createPinia } from "pinia";
import { createApp } from "vue";

import App from "@/App.vue";
import { router } from "@/router";
import { useAuthStore } from "@/stores/auth";
import "@/style.css";

const app = createApp(App);
const pinia = createPinia();

app.use(pinia);
// Restore the Session from the HttpOnly refresh cookie; the router guard awaits the result.
void useAuthStore(pinia).bootstrap();
app.use(router);
app.mount("#app");

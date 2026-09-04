import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";

import { AppShell } from "@/components/layout/AppShell";
import { DiscoverPage } from "@/pages/DiscoverPage";
import { ModelPage } from "@/pages/ModelPage";
import { ProfilePage } from "@/pages/ProfilePage";
import { PortfolioPage } from "@/pages/PortfolioPage";
import { DocsPage } from "@/pages/DocsPage";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      refetchOnWindowFocus: false,
    },
  },
});

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route element={<AppShell />}>
            <Route index element={<ModelPage />} />
            <Route path="/discover" element={<DiscoverPage />} />
            <Route path="/stocks/:symbol" element={<ProfilePage />} />
            <Route path="/portfolio" element={<PortfolioPage />} />
            <Route path="/docs" element={<DocsPage />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  );
}

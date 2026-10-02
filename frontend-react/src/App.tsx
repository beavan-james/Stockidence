import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";

import { AppShell } from "@/components/layout/AppShell";
import { DocsPage } from "@/pages/DocsPage";
import { MarketPage } from "@/pages/MarketPage";
import { ModelPage } from "@/pages/ModelPage";
import { RankingsPage } from "@/pages/RankingsPage";
import { StockPage } from "@/pages/StockPage";

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
            <Route index element={<RankingsPage />} />
            <Route path="/stocks/:symbol" element={<StockPage />} />
            <Route path="/model" element={<ModelPage />} />
            <Route path="/market" element={<MarketPage />} />
            <Route path="/docs" element={<DocsPage />} />
            {/* Old routes from the previous layout */}
            <Route path="/discover" element={<Navigate to="/market" replace />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  );
}

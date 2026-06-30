import { createBrowserRouter } from "react-router";
import { AppShell } from "./components/AppShell";
import { ClaimsList } from "./components/ClaimsList";
import { SubmitClaim } from "./components/SubmitClaim";
import { DecisionDetail } from "./components/DecisionDetail";

export const router = createBrowserRouter([
  {
    path: "/",
    Component: AppShell,
    children: [
      { index: true, Component: ClaimsList },
      { path: "submit", Component: SubmitClaim },
      { path: "claims/:claimId", Component: DecisionDetail },
    ],
  },
]);

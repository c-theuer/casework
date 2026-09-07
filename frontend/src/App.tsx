import { NavLink, Route, Routes } from "react-router-dom";
import "./App.css";
import { Checkout } from "./pages/Checkout";
import { Queue } from "./pages/Queue";

export default function App() {
  return (
    <div className="app">
      <nav className="nav">
        <NavLink to="/" end>
          Checkout
        </NavLink>
        <NavLink to="/queue">Fraud-ops queue</NavLink>
      </nav>
      <Routes>
        <Route path="/" element={<Checkout />} />
        <Route path="/queue" element={<Queue />} />
      </Routes>
    </div>
  );
}

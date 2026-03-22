import type { Variants, Transition } from "framer-motion";

/** Standard spring transition */
export const spring: Transition = {
  type: "spring",
  stiffness: 300,
  damping: 30,
};

/** Fade in from below */
export const fadeInUp: Variants = {
  hidden: { opacity: 0, y: 20 },
  visible: { opacity: 1, y: 0, transition: { duration: 0.4, ease: "easeOut" } },
};

/** Fade in */
export const fadeIn: Variants = {
  hidden: { opacity: 0 },
  visible: { opacity: 1, transition: { duration: 0.3 } },
};

/** Slide in from right (for panels) */
export const slideInRight: Variants = {
  hidden: { x: "100%", opacity: 0 },
  visible: { x: 0, opacity: 1, transition: { type: "spring", damping: 25, stiffness: 200 } },
  exit: { x: "100%", opacity: 0, transition: { duration: 0.2 } },
};

/** Stagger children animation */
export const staggerContainer: Variants = {
  hidden: { opacity: 0 },
  visible: {
    opacity: 1,
    transition: { staggerChildren: 0.05 },
  },
};

/** Stagger child item */
export const staggerItem: Variants = {
  hidden: { opacity: 0, y: 10 },
  visible: { opacity: 1, y: 0 },
};

/** Number counter animation config */
export const numberTransition: Transition = {
  duration: 0.8,
  ease: "easeOut",
};

/** Pulse animation for alert cells */
export const alertPulse: Variants = {
  idle: { scale: 1 },
  pulse: {
    scale: [1, 1.02, 1],
    transition: { duration: 2, repeat: Infinity, ease: "easeInOut" },
  },
};

/** Card hover effect */
export const cardHover: Variants = {
  rest: { scale: 1, boxShadow: "0 1px 3px rgba(0,0,0,0.1)" },
  hover: { scale: 1.01, boxShadow: "0 4px 12px rgba(0,0,0,0.15)", transition: spring },
};

/** Page transition */
export const pageTransition: Variants = {
  initial: { opacity: 0, y: 8 },
  animate: { opacity: 1, y: 0, transition: { duration: 0.3, ease: "easeOut" } },
  exit: { opacity: 0, y: -8, transition: { duration: 0.2 } },
};

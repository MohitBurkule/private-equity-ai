//! Port of RateLimiter (apps/api/app/ratelimit.py): per-tenant token bucket, one process.
//! RATE_LIMIT_PER_MIN sets the bucket size and refill rate; 0 disables it.

use std::collections::HashMap;
use std::sync::Mutex;
use std::time::Instant;

pub struct RateLimiter {
    rate: f64,
    cap: f64,
    state: Mutex<HashMap<String, (f64, Instant)>>,
}

impl RateLimiter {
    pub fn new(per_minute: u32) -> Self {
        Self {
            rate: per_minute as f64 / 60.0,
            cap: per_minute as f64,
            state: Mutex::new(HashMap::new()),
        }
    }

    pub fn allow(&self, key: &str) -> bool {
        self.allow_at(key, Instant::now())
    }

    fn allow_at(&self, key: &str, now: Instant) -> bool {
        if self.cap <= 0.0 {
            return true;
        }
        let mut state = self.state.lock().unwrap_or_else(|e| e.into_inner());
        let (tokens, last) = state.get(key).copied().unwrap_or((self.cap, now));
        let refilled = (tokens + now.duration_since(last).as_secs_f64() * self.rate).min(self.cap);
        if refilled < 1.0 {
            state.insert(key.to_owned(), (refilled, now));
            return false;
        }
        state.insert(key.to_owned(), (refilled - 1.0, now));
        true
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::time::Duration;

    #[test]
    fn bucket_drains_then_refills() {
        let rl = RateLimiter::new(60); // 1 token per second, cap 60
        let t0 = Instant::now();
        for _ in 0..60 {
            assert!(rl.allow_at("t", t0));
        }
        assert!(!rl.allow_at("t", t0));
        assert!(rl.allow_at("t", t0 + Duration::from_secs(1)));
        assert!(rl.allow_at("other", t0), "buckets are per tenant");
    }

    #[test]
    fn zero_disables() {
        let rl = RateLimiter::new(0);
        for _ in 0..1000 {
            assert!(rl.allow("t"));
        }
    }
}

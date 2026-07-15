package com.aigeneration.questionbank;

import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.aigeneration.questionbank.config.PythonWorkerProperties;
import com.aigeneration.questionbank.proxy.PythonWorkerProxyFilter;
import org.junit.jupiter.api.Test;
import org.springframework.mock.web.MockHttpServletRequest;

/**
 * Guards Java-owned import-task routes from being accidentally forwarded to the Python legacy API proxy.
 */
class PythonWorkerProxyFilterTest {
    private final TestablePythonWorkerProxyFilter filter =
            new TestablePythonWorkerProxyFilter(new PythonWorkerProperties());

    @Test
    void canonicalizationAndGlobalStandardizationRoutesBypassPythonProxy() {
        assertTrue(filter.bypasses("POST", "/api/import-tasks/task-1/canonicalization/preview"));
        assertTrue(filter.bypasses("POST", "/api/import-tasks/task-1/canonicalization/apply"));
        assertTrue(filter.bypasses("POST", "/api/import-tasks/task-1/canonicalization/rollback"));
        assertTrue(filter.bypasses("POST", "/api/import-tasks/task-1/standardization-jobs"));
        assertTrue(filter.bypasses("GET", "/api/import-tasks/task-1/standardization-jobs/job-1"));
        assertTrue(filter.bypasses("POST", "/api/import-tasks/task-1/standardization-jobs/job-1/retry-failed"));
    }

    @Test
    void legacyWorkerApiRemainsProxied() {
        assertFalse(filter.bypasses("GET", "/api/legacy-worker-capability"));
    }

    private static final class TestablePythonWorkerProxyFilter extends PythonWorkerProxyFilter {
        private TestablePythonWorkerProxyFilter(PythonWorkerProperties properties) {
            super(properties);
        }

        private boolean bypasses(String method, String path) {
            return shouldNotFilter(new MockHttpServletRequest(method, path));
        }
    }
}

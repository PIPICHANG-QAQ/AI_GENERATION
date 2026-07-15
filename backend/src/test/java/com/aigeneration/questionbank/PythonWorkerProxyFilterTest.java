package com.aigeneration.questionbank;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.aigeneration.questionbank.config.PythonWorkerProperties;
import com.aigeneration.questionbank.proxy.PythonWorkerProxyFilter;
import java.util.stream.Stream;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.Arguments;
import org.junit.jupiter.params.provider.MethodSource;
import org.springframework.mock.web.MockHttpServletRequest;

/**
 * Guards Java-owned import-task routes from being accidentally forwarded to the Python legacy API proxy.
 */
class PythonWorkerProxyFilterTest {
    private final TestablePythonWorkerProxyFilter filter =
            new TestablePythonWorkerProxyFilter(new PythonWorkerProperties());

    @Test
    void canonicalizationRoutesBypassPythonProxy() {
        assertTrue(filter.bypasses("POST", "/api/import-tasks/task-1/canonicalization/preview"));
        assertTrue(filter.bypasses("POST", "/api/import-tasks/task-1/canonicalization/apply"));
        assertTrue(filter.bypasses("POST", "/api/import-tasks/task-1/canonicalization/rollback"));
    }

    @ParameterizedTest(name = "{0} {1} bypass={2}")
    @MethodSource("standardizationRouteCases")
    void standardizationRoutesUseExactJavaOwnedBoundary(String method, String path, boolean expectedBypass) {
        assertEquals(expectedBypass, filter.bypasses(method, path));
    }

    private static Stream<Arguments> standardizationRouteCases() {
        return Stream.of(
                Arguments.of("POST", "/api/import-tasks/task-1/standardization-jobs", true),
                Arguments.of("GET", "/api/import-tasks/task-1/standardization-jobs/job-1", true),
                Arguments.of("POST", "/api/import-tasks/task-1/standardization-jobs/job-1/cancel", true),
                Arguments.of("POST", "/api/import-tasks/task-1/standardization-jobs/job-1/resume", true),
                Arguments.of("POST", "/api/import-tasks/task-1/standardization-jobs/job-1/retry-failed", true),
                Arguments.of("GET", "/api/import-tasks/task-1/standardization-jobs-legacy/job-1", false)
        );
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

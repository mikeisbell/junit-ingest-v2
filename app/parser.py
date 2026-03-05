import xml.etree.ElementTree as ET

from .models import TestCase, TestStatus, TestSuiteResult


class JUnitParseError(ValueError):
    pass


def parse_junit_xml(content: bytes) -> TestSuiteResult:
    """Parse JUnit XML content and return a TestSuiteResult."""
    try:
        root = ET.fromstring(content)
    except ET.ParseError as exc:
        raise JUnitParseError(f"Invalid XML: {exc}") from exc

    # Support both <testsuite> as root and <testsuites> wrapping a single suite
    if root.tag == "testsuites":
        suites = list(root.findall("testsuite"))
        if not suites:
            raise JUnitParseError("No <testsuite> element found in XML")
        suite = suites[0]
    elif root.tag == "testsuite":
        suite = root
    else:
        raise JUnitParseError(
            f"Expected root element <testsuite> or <testsuites>, got <{root.tag}>"
        )

    def _int_attr(attr: str, default: int = 0) -> int:
        try:
            return int(suite.get(attr, default))
        except (TypeError, ValueError):
            return default

    def _float_attr(attr: str, default: float = 0.0) -> float:
        try:
            return float(suite.get(attr, default))
        except (TypeError, ValueError):
            return default

    name = suite.get("name", "")
    if not name:
        raise JUnitParseError("The <testsuite> element is missing a 'name' attribute")

    total_tests = _int_attr("tests")
    total_failures = _int_attr("failures")
    total_errors = _int_attr("errors")
    total_skipped = _int_attr("skipped")
    elapsed_time = _float_attr("time")

    test_cases: list[TestCase] = []
    for tc in suite.findall("testcase"):
        tc_name = tc.get("name", "")

        failure_el = tc.find("failure")
        error_el = tc.find("error")
        skipped_el = tc.find("skipped")

        if failure_el is not None:
            status = TestStatus.failed
            failure_message = failure_el.get("message") or (failure_el.text or "").strip() or None
        elif error_el is not None:
            status = TestStatus.error
            failure_message = error_el.get("message") or (error_el.text or "").strip() or None
        elif skipped_el is not None:
            status = TestStatus.skipped
            failure_message = skipped_el.get("message") or None
        else:
            status = TestStatus.passed
            failure_message = None

        test_cases.append(TestCase(name=tc_name, status=status, failure_message=failure_message))

    return TestSuiteResult(
        name=name,
        total_tests=total_tests,
        total_failures=total_failures,
        total_errors=total_errors,
        total_skipped=total_skipped,
        elapsed_time=elapsed_time,
        test_cases=test_cases,
    )

"""
Tests for the Project Manager component.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import AnyUrl
from qdrant_loader.config.models import ProjectConfig, ProjectsConfig
from qdrant_loader.config.sources import SourcesConfig
from qdrant_loader.config.state import StateManagementConfig
from qdrant_loader.connectors.git.config import GitRepoConfig
from qdrant_loader.core.project_manager import ProjectContext, ProjectManager
from qdrant_loader.core.state.models import Project
from qdrant_loader.core.state.state_manager import StateManager
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.fixture
def sample_projects_config():
    """Create a sample projects configuration for testing."""
    git_config = GitRepoConfig(
        source_type="git",
        source="test-repo",
        base_url=AnyUrl("https://github.com/test/repo.git"),
        branch="main",
        token="test-token",
        temp_dir="/tmp/test",
        file_types=["md", "py"],
    )

    sources_config = SourcesConfig()
    sources_config.git = {"test-repo": git_config}

    project_config = ProjectConfig(
        project_id="test-project",
        display_name="Test Project",
        description="A test project",
        sources=sources_config,
    )

    projects_config = ProjectsConfig()
    projects_config.projects = {"test-project": project_config}

    return projects_config


@pytest.fixture
def project_manager(sample_projects_config):
    """Create a project manager instance for testing."""
    return ProjectManager(
        projects_config=sample_projects_config,
        global_collection_name="global_collection",
    )


@pytest.mark.asyncio
async def test_project_manager_initialization(project_manager):
    """Test that project manager initializes correctly."""
    # Mock session
    mock_session = AsyncMock(spec=AsyncSession)
    mock_session.execute = AsyncMock()
    mock_session.commit = AsyncMock()

    # Mock database query results - create a proper mock result
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_session.execute.return_value = mock_result

    # Initialize project manager
    await project_manager.initialize(mock_session)

    # Verify initialization
    assert project_manager._initialized is True
    assert len(project_manager._project_contexts) == 1
    assert "test-project" in project_manager._project_contexts


@pytest.mark.asyncio
async def test_project_context_creation(project_manager):
    """Test that project contexts are created correctly."""
    # Mock session
    mock_session = AsyncMock(spec=AsyncSession)
    mock_session.execute = AsyncMock()
    mock_session.commit = AsyncMock()

    # Mock database query results - create a proper mock result
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_session.execute.return_value = mock_result

    # Initialize project manager
    await project_manager.initialize(mock_session)

    # Get project context
    context = project_manager.get_project_context("test-project")

    # Verify context
    assert context is not None
    assert context.project_id == "test-project"
    assert context.display_name == "Test Project"
    assert context.description == "A test project"
    assert context.collection_name == "global_collection"


def test_project_metadata_injection(project_manager):
    """Test that project metadata is injected correctly."""
    # Create a project context manually for testing
    context = ProjectContext(
        project_id="test-project",
        display_name="Test Project",
        description="A test project",
        collection_name="global_collection",  # Use global collection name
    )
    project_manager._project_contexts["test-project"] = context

    # Test metadata injection
    original_metadata = {"title": "Test Document", "author": "Test Author"}
    enhanced_metadata = project_manager.inject_project_metadata(
        "test-project", original_metadata
    )

    # Verify enhanced metadata
    assert enhanced_metadata["title"] == "Test Document"
    assert enhanced_metadata["author"] == "Test Author"
    assert enhanced_metadata["project_id"] == "test-project"
    assert enhanced_metadata["project_name"] == "Test Project"
    assert enhanced_metadata["project_description"] == "A test project"
    assert enhanced_metadata["collection_name"] == "global_collection"


def test_project_validation(project_manager):
    """Test project validation methods."""
    # Create a project context manually for testing
    context = ProjectContext(project_id="test-project", display_name="Test Project")
    project_manager._project_contexts["test-project"] = context

    # Test validation
    assert project_manager.validate_project_exists("test-project") is True
    assert project_manager.validate_project_exists("non-existent") is False


def test_project_collection_name_resolution(project_manager):
    """Test that collection names are resolved correctly."""
    # Create project contexts - all should use global collection name
    context1 = ProjectContext(
        project_id="project-1",
        display_name="Project 1",
        collection_name="global_collection",  # All projects use global collection
    )
    context2 = ProjectContext(
        project_id="project-2",
        display_name="Project 2",
        collection_name="global_collection",  # All projects use global collection
    )

    project_manager._project_contexts["project-1"] = context1
    project_manager._project_contexts["project-2"] = context2

    # Test collection name resolution - all should return global collection name
    assert (
        project_manager.get_project_collection_name("project-1") == "global_collection"
    )
    assert (
        project_manager.get_project_collection_name("project-2") == "global_collection"
    )
    assert project_manager.get_project_collection_name("non-existent") is None


def test_project_listing(project_manager):
    """Test project listing functionality."""
    # Create multiple project contexts
    context1 = ProjectContext(project_id="project-1", display_name="Project 1")
    context2 = ProjectContext(project_id="project-2", display_name="Project 2")

    project_manager._project_contexts["project-1"] = context1
    project_manager._project_contexts["project-2"] = context2

    # Test listing
    project_ids = project_manager.list_project_ids()
    assert len(project_ids) == 2
    assert "project-1" in project_ids
    assert "project-2" in project_ids

    # Test getting all contexts
    all_contexts = project_manager.get_all_project_contexts()
    assert len(all_contexts) == 2
    assert all_contexts["project-1"].display_name == "Project 1"
    assert all_contexts["project-2"].display_name == "Project 2"


@pytest.mark.asyncio
async def test_multi_project_shared_collection_name_allowed():
    """Two projects should be persisted even when sharing global collection name."""
    git_config_1 = GitRepoConfig(
        source_type="git",
        source="repo-1",
        base_url=AnyUrl("https://github.com/test/repo-1.git"),
        branch="main",
        token="test-token",
        temp_dir="/tmp/test-1",
        file_types=["md"],
    )
    git_config_2 = GitRepoConfig(
        source_type="git",
        source="repo-2",
        base_url=AnyUrl("https://github.com/test/repo-2.git"),
        branch="main",
        token="test-token",
        temp_dir="/tmp/test-2",
        file_types=["md"],
    )

    sources_1 = SourcesConfig()
    sources_1.git = {"repo-1": git_config_1}
    sources_2 = SourcesConfig()
    sources_2.git = {"repo-2": git_config_2}

    project_1 = ProjectConfig(
        project_id="project-1",
        display_name="Project 1",
        description="First project",
        sources=sources_1,
    )
    project_2 = ProjectConfig(
        project_id="project-2",
        display_name="Project 2",
        description="Second project",
        sources=sources_2,
    )

    projects_config = ProjectsConfig()
    projects_config.projects = {
        "project-1": project_1,
        "project-2": project_2,
    }

    state_manager = StateManager(StateManagementConfig(database_path=":memory:"))
    await state_manager.initialize()
    try:
        async with await state_manager.get_session() as session:
            manager = ProjectManager(
                projects_config=projects_config,
                global_collection_name="shared_collection",
            )
            await manager.initialize(session)

            result = await session.execute(select(Project))
            projects = result.scalars().all()

            assert len(projects) == 2
            assert all(p.collection_name == "shared_collection" for p in projects)
    finally:
        await state_manager.dispose()


@pytest.mark.asyncio
async def test_outdated_state_db_error_surfaces_actionable_hint(project_manager):
    """Autoflush IntegrityError should be converted to a clear recovery hint."""
    mock_session = AsyncMock(spec=AsyncSession)
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_session.execute.return_value = mock_result

    async def _raise_autoflush_error(*_args, **_kwargs):
        raise IntegrityError(
            statement="INSERT INTO projects ...",
            params={},
            orig=Exception("UNIQUE constraint failed: projects.collection_name"),
        )

    project_manager._update_project_sources = _raise_autoflush_error  # type: ignore[method-assign]

    context = ProjectContext(
        project_id="test-project",
        display_name="Test Project",
        description="A test project",
        collection_name="global_collection",
        config=project_manager.projects_config.projects["test-project"],
    )

    with pytest.raises(ValueError, match="State DB schema is outdated"):
        await project_manager._ensure_project_in_database(  # type: ignore[attr-defined]
            mock_session,
            context,
            project_manager.projects_config.projects["test-project"],
        )

    mock_session.rollback.assert_awaited_once()


def _session_with_existing_sources(existing_sources):
    """Build a mocked AsyncSession whose select().scalars().all() returns
    the given ProjectSource-like rows."""
    session = AsyncMock(spec=AsyncSession)
    execute_result = MagicMock()
    execute_result.scalars.return_value.all.return_value = existing_sources
    session.execute.return_value = execute_result
    return session


@pytest.mark.asyncio
async def test_update_project_sources_clears_checkpoint_on_config_change(
    project_manager, sample_projects_config
):
    """When a source's configuration hash changes, any saved checkpoint for that
    source must be dropped — it was computed against the old query/config and
    would otherwise silently resume the new run mid-page against stale state."""
    from unittest.mock import patch

    from qdrant_loader.core.state.models import ProjectSource

    project_id = "test-project"
    config = sample_projects_config.projects[project_id]

    existing_source = MagicMock(spec=ProjectSource)
    existing_source.source_type = "git"
    existing_source.source_name = "test-repo"
    existing_source.config_hash = "stale-hash-that-will-not-match"

    session = _session_with_existing_sources([existing_source])

    with patch(
        "qdrant_loader.core.state.checkpoint_manager.CheckpointManager"
    ) as checkpoint_manager_cls:
        clear_checkpoint = AsyncMock()
        checkpoint_manager_cls.return_value.clear_checkpoint = clear_checkpoint

        await project_manager._update_project_sources(session, project_id, config)

    clear_checkpoint.assert_awaited_once_with(project_id, "git", "test-repo")


@pytest.mark.asyncio
async def test_update_project_sources_keeps_checkpoint_when_config_unchanged(
    project_manager, sample_projects_config
):
    """No config change → no checkpoint should be touched."""
    from unittest.mock import patch

    from qdrant_loader.core.state.models import ProjectSource

    project_id = "test-project"
    config = sample_projects_config.projects[project_id]
    git_source_config = config.sources.git["test-repo"]
    real_hash = project_manager._calculate_source_config_hash(git_source_config)

    existing_source = MagicMock(spec=ProjectSource)
    existing_source.source_type = "git"
    existing_source.source_name = "test-repo"
    existing_source.config_hash = real_hash

    session = _session_with_existing_sources([existing_source])

    with patch(
        "qdrant_loader.core.state.checkpoint_manager.CheckpointManager"
    ) as checkpoint_manager_cls:
        clear_checkpoint = AsyncMock()
        checkpoint_manager_cls.return_value.clear_checkpoint = clear_checkpoint

        await project_manager._update_project_sources(session, project_id, config)

    clear_checkpoint.assert_not_awaited()


@pytest.mark.asyncio
async def test_update_project_sources_keeps_checkpoint_for_legacy_row_without_hash(
    project_manager, sample_projects_config
):
    """A pre-existing source that never had a config_hash computed (legacy DB
    row, upgrading into hash tracking for the first time) should not have its
    checkpoint wiped just because the hash column is being populated now."""
    from unittest.mock import patch

    from qdrant_loader.core.state.models import ProjectSource

    project_id = "test-project"
    config = sample_projects_config.projects[project_id]

    existing_source = MagicMock(spec=ProjectSource)
    existing_source.source_type = "git"
    existing_source.source_name = "test-repo"
    existing_source.config_hash = None

    session = _session_with_existing_sources([existing_source])

    with patch(
        "qdrant_loader.core.state.checkpoint_manager.CheckpointManager"
    ) as checkpoint_manager_cls:
        clear_checkpoint = AsyncMock()
        checkpoint_manager_cls.return_value.clear_checkpoint = clear_checkpoint

        await project_manager._update_project_sources(session, project_id, config)

    clear_checkpoint.assert_not_awaited()

from sqlalchemy import select

from app.db.session import session_scope
from app.domain.exceptions import NotFoundError
from app.models import Concept, ConceptRelation, Course
from app.schemas import ConceptGraphResponse, ConceptRelationResponse, ConceptResponse, DemoDataStatusResponse
from app.services.demo_data_service import DEMO_CONCEPT_SLUGS, DemoDataService


class CourseService:
    def __init__(self, database_url: str | None = None) -> None:
        self.database_url = database_url

    def get_concept_graph(self, course_id: int) -> ConceptGraphResponse:
        self.ensure_demo_course_loaded()
        with session_scope(self.database_url) as session:
            course = session.get(Course, course_id)
            if course is None:
                raise NotFoundError("Course", course_id)
            concept_query = select(Concept).where(Concept.course_id == course.id)
            if course.is_demo:
                concept_query = concept_query.where(Concept.slug.in_(DEMO_CONCEPT_SLUGS))
            concepts = session.scalars(concept_query.order_by(Concept.id)).all()
            concept_ids = [concept.id for concept in concepts]
            relations = []
            if concept_ids:
                relations = session.scalars(
                    select(ConceptRelation)
                    .where(
                        ConceptRelation.source_concept_id.in_(concept_ids),
                        ConceptRelation.target_concept_id.in_(concept_ids),
                    )
                    .order_by(ConceptRelation.id)
                ).all()
            return ConceptGraphResponse(
                course_id=course.id,
                course_title=course.title,
                concepts=[ConceptResponse.model_validate(concept) for concept in concepts],
                relations=[ConceptRelationResponse.model_validate(relation) for relation in relations],
            )

    def ensure_demo_course_loaded(self) -> DemoDataStatusResponse:
        service = DemoDataService(database_url=self.database_url)
        status_response = service.get_status()
        if status_response.is_loaded:
            return status_response
        return service.load_demo_data().demo_data
